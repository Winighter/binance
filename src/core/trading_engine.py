import logging
from decimal import Decimal
import settings as app_config
from binance.exceptions import BinanceAPIException
from ..shared.state_manager import PositionState
from ..shared.enums import OrderSide, PositionSide, LongSignal, AssetType, FutureClientPeriod
from ..analysis.signals import TradingSignals
from ..analysis.test import PullbackAnalyzer
from ..analysis.ctr import CommodityTrendReactor
from ..analysis.renderer import plot_line_chart
from ..shared.errors import MARGIN_INSUFFICIENT_CODE, BinanceClientException
from typing import List
from ..config import *
from decimal import Decimal, getcontext
from ..api.binance_setup_manager import BinanceSetupManager
import pandas as pd 

logger = logging.getLogger("TRADING_ENGINE")


class TradingEngine:

    def __init__(self, binance_client, trading_manager, positions:PositionState, leverage:Decimal,
                symbol: str, asset: List[dict], ohlcv_prices:List[List[Decimal]]):
        self.symbol = symbol
        self.binance_client = binance_client
        self.trading_manager = trading_manager
        self.positions = positions
        self.open_prices=ohlcv_prices[0]
        self.high_prices=ohlcv_prices[1]
        self.low_prices=ohlcv_prices[2]
        self.close_prices=ohlcv_prices[3]
        self.volume_prices=ohlcv_prices[4]
        self.asset = asset
        self.leverage = Decimal(str(leverage))

        # ⚙️ CTR 인스턴스 초기화 (추가)
        self.ctr_analyzer = CommodityTrendReactor(
            cci_len=25,  # 설정값으로 변경 필요 (현재는 25, 20 사용)
            trail_len=20,
            upper=50,
            lower=-50
        )

        self.balance = None
        self.available_balance = None

        self.initialize_bot_state()
        self.update_balance()

    def initialize_bot_state(self):
        try:
            positions_info = self.binance_client.futures_position_information(self.symbol)
            if positions_info:
                for pos in positions_info:
                    if Decimal(pos['positionAmt']) != Decimal('0'):
                        position_side = pos['positionSide']
                        amount = Decimal(pos['positionAmt'])
                        entry_price = Decimal(pos['entryPrice'])
                        if position_side == PositionSide.LONG.value:
                            logger.info("Found an open LONG position during initialization.")
                            self.positions.long = entry_price
                            self.positions.long_amount = abs(amount)
                            self.positions.long_entry_price = entry_price

            orders = self.binance_client.futures_get_all_orders()
            if orders:
                for order in orders:
                    if order['type'] == 'STOP_MARKET' and order['status'] == 'NEW':
                        order_side = order['side']
                        position_side = order['positionSide']
                        if position_side == PositionSide.LONG.value and order_side == OrderSide.SELL.value:
                            self.positions.long_stop_loss_order_id = order['orderId']
                            self.positions.long_stop_loss = Decimal(order['stopPrice'])
                            logger.info(f"Found existing long stop-loss order {order['orderId']} {Decimal(order['stopPrice'])} during initialization.")
            # self.analyze_whale(self.symbol, FutureClientPeriod._5M)
            # logger.info(f"Funding Fee is settled every 8 hours at 00:00, 08:00, and 16:00 UTC (09:00, 17:00, 01:00 KST).")
        except Exception as e:
            logger.error(f"Failed to initialize bot state from Binance: {e}", exc_info=True)

    def _verify_order_and_state(self) -> bool:
        try:
            position_info = self.binance_client.futures_position_information(symbol=self.symbol)
            
            if len(position_info) > 0 and position_info[0]['positionSide'] == PositionSide.LONG.value:
                logger.info("CONFIRMATION: A new position was successfully opened despite the API error.")
                self.initialize_bot_state() 
                return True

            open_orders = self.binance_client.futures_get_all_orders(symbol=self.symbol)
            if len(open_orders) > 0:
                logger.info(f"CONFIRMATION: There are {len(open_orders)} open orders. The order might still be processing.")
                return True

            logger.error("CONFIRMATION: No position was opened and no open orders found. The order failed completely.")
            return False

        except BinanceClientException as e:
            logger.critical(f"FATAL: Failed to verify order status due to a critical API error. Error: {e}")
            return False
        
        except Exception as e:
            logger.critical(f"FATAL: Unexpected error during order verification: {e}", exc_info=True)
            return False

    def _get_quantity_precision(self, symbol: str) -> int:
        try:
            symbol_info = self.binance_client.get_symbol_info(symbol=self.symbol)
            if symbol_info and 'filters' in symbol_info:
                for f in symbol_info['filters']:
                    if f['filterType'] == 'LOT_SIZE':
                        step_size = Decimal(f['stepSize'])
                        precision = max(0, -step_size.as_tuple().exponent)
                        return precision
        except Exception as e:
            logger.error(f"Failed to get quantity precision for {symbol}: {e}", exc_info=True)
        return 0

    def _adjust_quantity_by_precision(self, symbol: str, quantity: Decimal) -> Decimal:
        precision = self._get_quantity_precision(symbol)
        if precision is not None:
            getcontext().prec = 28  # 높은 정밀도로 설정
            quantizer = Decimal('1e-{}'.format(precision))
            return quantity.quantize(quantizer)
        return quantity

    def get_position_quantity(self, price: Decimal, stop_loss_price: Decimal):
        try:
            # 1. 최대 허용 손실 5%에 해당하는 가격 계산
            MAX_LOSS_PERCENTAGE = Decimal('0.05')
            # 롱 포지션 기준: 진입 가격에서 5% 하락한 가격
            max_loss_price = price * (Decimal('1') - MAX_LOSS_PERCENTAGE)
            # 2. 손절 가격 보정 (현재 손절 가격이 5% 가격보다 낮다면, 5% 가격으로 상향 조정)
            adjusted_sl_price = max(stop_loss_price, max_loss_price)

            # 로그 추가 (디버깅/정보용)
            if adjusted_sl_price != stop_loss_price:
                logger.info(f"SL price adjusted: Original SL {stop_loss_price:.4f} was below 5% max loss price {max_loss_price:.4f}. New SL: {adjusted_sl_price:.4f}")

            quantity = self.trading_manager.calculate_quantity_with_risk_management(
                price=price,
                symbol=self.symbol,
                balance_usdt=self.balance,
                stop_loss_price=adjusted_sl_price,
                risk_percentage=app_config.MAX_RISK_RATIO,
            )
            # 2. 포지션 규모(총 가치) 계산
            position_value = quantity * price * self.leverage

            # 3. 포지션 비율 상한선(20%) 설정
            max_position_value = self.balance * self.leverage * Decimal(str(app_config.MAX_POSITION_RATIO / 100))

            # 4. 포지션 규모가 상한선을 초과하는지 확인하고 조정 (첫 주문 시)
            if not self.positions.long:
                if position_value > max_position_value:
                    # 현재 이용가능한 자산이 있는지 확인
                    if max_position_value < (self.available_balance * self.leverage):
                        # 상한선에 맞게 새로운 수량 계산
                        new_quantity = max_position_value / price
                        # 5. 수량 정밀도에 맞게 조정
                        adjusted_quantity = self._adjust_quantity_by_precision(
                            symbol=self.symbol,
                            quantity=new_quantity
                        )
                        return adjusted_quantity, adjusted_sl_price

                # 👇👇👇 [수정/추가된 부분: 한도를 초과하지 않은 경우] 👇👇👇
                # 한도를 초과하지 않은 경우: risk_management로 계산된 quantity를 그대로 사용
                adjusted_quantity = self._adjust_quantity_by_precision(
                    symbol=self.symbol,
                    quantity=quantity # 리스크 관리 기반으로 계산된 원래 수량
                )
                return adjusted_quantity, adjusted_sl_price

            elif self.positions.long:
                current_position_value = Decimal('0')
                # 2. 현재 보유 중인 포지션 가치 계산
                if self.positions.long_amount and self.positions.long_entry_price:
                    current_position_value = self.positions.long_amount * self.positions.long_entry_price

                    # 4. 추가 매수 가능한 포지션 가치 계산
                    remaining_position_value = max_position_value - current_position_value

                    if remaining_position_value <= Decimal('0'):
                        logger.info("Cannot add to the position. The maximum position limit has been reached.")
                        return Decimal('0')

                    # 5. 리스크 기반 수량과 추가 매수 가능 수량 중 더 작은 값 선택
                    #    (가치 기반으로 변환하여 비교)
                    risk_based_value = quantity * price
                    
                    # 실제 매수할 포지션 가치
                    target_value = min(risk_based_value, remaining_position_value)

                    # 6. 최종 수량 계산 및 정밀도 조정
                    final_quantity = target_value / price
                    
                    # 현재 이용가능한 자산이 있는지 확인
                    if target_value > (self.available_balance * self.leverage):
                        # 자산이 부족하면 이용가능한 자산 내에서만 구매
                        final_quantity = (self.available_balance * self.leverage) / price

                    adjusted_quantity = self._adjust_quantity_by_precision(
                        symbol=self.symbol,
                        quantity=final_quantity
                    )
                    
                    return adjusted_quantity


        except Exception as e:
            logger.error(f"QUANTITY ERROR: Failed to calculate order quantity: {e}")
            return 0

    def get_cvd(self, symbol:str):
        fat = self.binance_client._futures_aggregate_trades(symbol)
        logger.info(f"Length: {len(fat)}")

    def _pullback_analyzer(self, opens, highs, lows, closes):

        analyzer = PullbackAnalyzer(opens, highs, lows, closes)
        analysis_data = analyzer.get_last_analysis() # 수정된 test.py 로직에 의해 빈 딕셔너리가 올 수 있음

        # # --- 수정된 출력 및 확인 로직 (시작/끝 가격 포함) ---
        if analysis_data:
            up_move = analysis_data.get('up_move')
            down_move = analysis_data.get('down_move')

            if up_move:
                logger.info(f"🟢 {up_move.get('start_bar')}-{up_move.get('end_bar')}, {up_move['size']:.2f}% (PB: {up_move['pb_lb_size']:.2f}~{up_move['pb_ub_size']:.2f}%)")
        
            if down_move:
                logger.info(f"🔴 {down_move.get('start_bar')}-{down_move.get('end_bar')}, {down_move['size']:.2f}% (PB: {down_move['pb_lb_size']:.2f}~{down_move['pb_ub_size']:.2f}%)")
        else:
            logger.info(f"analysis_data is {analysis_data}")

    def process_stream_data(self, res):
        try:
            if not res:
                return
            if 'stream' in res and 'data' in res:
                stream_name = res.get('stream')
                data = res.get('data')

                if stream_name == f"{self.symbol.lower()}@kline_{app_config.KLINE_INTERVAL}":

                    kline_data = data.get('k')
                    if kline_data.get('x'):

                        opens, highs, lows, closes, volumes = self.update_candle_data(kline_data)

                        try:
                            long_signal = TradingSignals(opens, highs, lows, closes, volumes).long_signal
                            if long_signal is not LongSignal.NO_SIGNAL:
                                logger.info(f"long_signal: {long_signal}")

                        except Exception as e:
                            logger.error(f"Failed to find signal. {e}", exc_info=True)
                            return

                        if not app_config.TEST_MODE:
                            self.pullback_execute_long_trade(long_signal, lows[-1], closes[-1])

        except Exception as e:
            logger.error(f"Unexpected error during data processing: {e}", exc_info=True)

    def process_user_data(self, user_data):
        try:
            event_type = user_data.get('e')
            if event_type == 'ORDER_TRADE_UPDATE':
                order_status = user_data['o'].get('X')
                position_side = user_data['o'].get('ps')
                order_id = user_data['o'].get('i')

                if order_status == 'FILLED':
                    if order_id == self.positions.long_stop_loss_order_id:
                        logger.info("Long stop-loss order has been filled. Resetting local state.")
                        self.positions = PositionState()

                    elif position_side == PositionSide.LONG and self.positions.long:
                        logger.info(f"Position ({position_side}) liquidation confirmed. Proceeding to cancel the stop-loss order.")

                        if position_side == PositionSide.LONG and self.positions.long_stop_loss_order_id:
                            self.trading_manager.cancel_order(
                                symbol=self.symbol,
                                order_id=self.positions.long_stop_loss_order_id
                            )
                        self.update_balance()
                        self.positions = PositionState()
            
            if event_type == 'ACCOUNT_UPDATE':
                for position in user_data['a']['P']:
                    if position['s'] == self.symbol and Decimal(position['pa']) == 0:
                        logger.info("Account update confirmed position liquidation. Resetting local state.")
                        self.positions = PositionState()

        except Exception as e:
            logger.error(f"Unexpected error during user data processing: {e}", exc_info=True)

    def update_candle_data(self, ohlcv_data):
        open = Decimal(str(ohlcv_data.get('o')))
        high = Decimal(str(ohlcv_data.get('h')))
        low = Decimal(str(ohlcv_data.get('l')))
        close = Decimal(str(ohlcv_data.get('c')))
        volume = Decimal(str(ohlcv_data.get('v')))

        self.open_prices.append(open)
        self.high_prices.append(high)
        self.low_prices.append(low)
        self.close_prices.append(close)
        self.volume_prices.append(volume)

        if len(self.close_prices) > KLINE_LIMIT:
            self.open_prices.pop(0)
            self.high_prices.pop(0)
            self.low_prices.pop(0)
            self.close_prices.pop(0)
            self.volume_prices.pop(0)

        return self.open_prices, self.high_prices, \
            self.low_prices, self.close_prices, self.volume_prices

    def update_balance(self, asset_type:str = AssetType.USDT.value):
        asset = BinanceSetupManager._fetch_balance(self)
        if asset is None:
            return logger.warning(f"Your balance is empty. It's not serious, but you can't proceed with the transaction.")
        try:
            for balance in asset:
                if asset_type in balance.keys():
                    data = balance.get(asset_type)
                    balance = data.get('balance')
                    availableBalance = data.get('availableBalance')
                    # crossWalletBalance = data.get('crossWalletBalance')
                    # crossUnPnl = data.get('crossUnPnl')
                    # maxWithdrawAmount = data.get('maxWithdrawAmount')
                    self.balance = balance
                    self.available_balance = availableBalance
                    logger.info(f"Balance successfully updated. Balance: {self.balance:.2f} Available balance: {self.available_balance:.2f} {asset_type}")
        except Exception as e:
            logger.error(f"Error while updating balance: {e}", exc_info=True)

    def get_list_key_data(self, data:list, key:str):

        if len(data) == 0:
            return logger.warning(f"Data is Empty or {len(data)}")
        result = []
        for d in data:
            a = Decimal(str(d.get(key)))
            result.append(a)
        return result

    def analyze_whale(self, symbol:str, ls_period: FutureClientPeriod):

        # 8시간 간격
        funding_rates = self.binance_client._futures_funding_rate(symbol)
        fr = self.get_list_key_data(funding_rates, "fundingRate")
        funding_rate = Decimal(str(funding_rates[-1].get("fundingRate")))

        ls_period = ls_period.value

        # 미결제 약정
        open_interest = list(self.binance_client._futures_open_interest(symbol, ls_period))
        oi = self.get_list_key_data(open_interest, 'sumOpenInterest')

        _accounts = self.binance_client._futures_top_longshort_account_ratio(symbol, ls_period)
        _a = self.get_list_key_data(_accounts, 'longShortRatio')
        _account = Decimal(str(_accounts[-1].get("longShortRatio")))

        _positions = self.binance_client._futures_top_longshort_position_ratio(symbol, ls_period)
        _p = self.get_list_key_data(_positions, 'longShortRatio')
        _position = Decimal(str(_positions[-1].get("longShortRatio")))

        _globals = self.binance_client._futures_global_longshort_ratio(symbol, ls_period)
        _g = self.get_list_key_data(_globals, 'longShortRatio')
        _global = Decimal(str(_globals[-1].get("longShortRatio")))

        _takers = self.binance_client._futures_taker_longshort_ratio(symbol, ls_period)
        _t = self.get_list_key_data(_takers, 'buySellRatio')
        _taker = Decimal(str(_takers[-1].get("buySellRatio")))

        all_data_to_plot = [fr, oi, _a, _p, _g, _t]
        labels = ["Funding rate (8h) / 09:00, 17:00, 01:00 KST", \
                f"Open Interest ({ls_period})", \
                f"Long/Short Accounts Ratio [Top] ({ls_period})", \
                f"Long/Short Positions Ratio [Top] ({ls_period})", \
                f"Long/Short Globals Ratio [All] ({ls_period})", \
                f"Long/Short Takers Ratio [All] ({ls_period})"]

        plot_line_chart(
            all_data=all_data_to_plot,
            line_labels=labels,
            main_title=f"Whale Trading Analysis ({symbol})",
            filename="whale_multi_chart.png"
        )

        STRONG_LONG_THRESHOLD = 1.2
        STRONG_SHORT_THRESHOLD = 0.8

        top_acc = _account
        top_pos = _position
        global_ls = _global
        taker_ls = _taker

        logger.info("--- 📊 Futures Market 4 Indicator Analysis Results ---")
        # 🐳 Whale, 👥 Public, 💼 Top Account, 🚀 Aggressive Order
        logger.info(f"1. Top Account Ratio (Top Account.):\t {top_acc:4f} 💼 (Top Trader Sentiment)")
        logger.info(f"2. Top Position Ratio (Top Position.):\t {top_pos:4f} 🐋 (Whale Capital Power)")
        logger.info(f"3. Global Ratio (Global Position.):\t {global_ls:4f} 👥 (Overall Market Sentiment)")
        logger.info(f"4. Taker Ratio (Taker Volume.):\t {taker_ls:4f} 🚀 (Aggressive Orders)")
        # logger.info(f"5. Funding Rate: {funding_rate}, Open Interest: {open_interest}")
        logger.info("-" * 35)

        # 1. Powerful Long Force Condition
        if top_pos >= STRONG_LONG_THRESHOLD and taker_ls > global_ls:
            logger.info("✅ [Strong Long Force Detected: Buy Pressure] ✅")
            logger.info("   - Whale position (Top Pos) is strongly skewed to Long (Capital secured).")
            logger.info("   - Taker orders (Taker LS) are higher than Global, indicating **aggressive market buying** by the force.")
            if top_acc < 1.0:
                logger.info("   - (Additional) Top Trader accounts are Short-dominated, increasing the possibility of **Short Squeeze induction**.")
            logger.info(f"[STRONG_LONG] Strong Long Force Dominance (Force is aggressively buying)")

        # 2. Powerful Short Force Condition
        elif top_pos <= STRONG_SHORT_THRESHOLD and taker_ls < global_ls:
            logger.info("🔻 [Strong Short Force Detected: Sell Pressure] 🔻")
            logger.info("   - Whale position (Top Pos) is strongly skewed to Short (Capital secured).")
            logger.info("   - Taker orders (Taker LS) are lower than Global, indicating **aggressive market selling** by the force.")
            if top_acc > 1.0:
                logger.info("   - (Additional) Top Trader accounts are Long-dominated, increasing the possibility of **Long Squeeze induction**.")
            logger.info(f"[STRONG_SHORT] Strong Short Force Dominance (Force is aggressively selling)")

        # 3. Whales are quiet, only the public is skewed (Liquidation Risk)
        elif (top_pos < STRONG_LONG_THRESHOLD and top_pos > STRONG_SHORT_THRESHOLD) and \
            (global_ls >= STRONG_LONG_THRESHOLD or global_ls <= STRONG_SHORT_THRESHOLD):
            
            logger.info("⚠️ [Retail Overheating: High Liquidation Risk] ⚠️")
            logger.info("   - Whales have not significantly increased positions, but the **general public (Global LS) is heavily skewed** to one side.")
            logger.info("   - If the current price movement is weak or consolidating, it may be **vulnerable to liquidation (squeeze) in the opposite direction**.")
            logger.info(f"[OVERHEATED_RETAIL] Retail position overheating (High risk of liquidation)")
            
        # 4. Wait-and-see or Neutral
        else:
            logger.info("⚪ [Current Market is Wait-and-see or Neutral] ⚪")
            logger.info("   - No clear whale positions or aggressive market orders detected.")
            logger.info("   - This is judged as waiting for the next trend or a lull.")
            logger.info(f"[NEUTRAL] Wait-and-see or Neutral (No clear force movement)")
        logger.info("-" * 35)
        logger.info("-" * 35)

    def create_buy_position(self, position:PositionSide, quantity: Decimal, current_price: Decimal, sl_price: Decimal):
        if position not in [PositionSide.LONG]:
            raise ValueError(f'Invalid value: {position}')
        if position in [PositionSide.LONG]:
            side = OrderSide.BUY
        try:
            order = self.trading_manager.create_market_order(
                symbol=self.symbol,
                side=side,
                positionSide=position,
                quantity=quantity
            )
            if order:
                # 손절매 주문 생성 전, 기존 포지션이 있을 경우 평균 단가 계산
                if self.positions.long_amount:
                    # 기존 총 가치 = 기존 수량 * 기존 단가
                    old_total_value = self.positions.long_amount * self.positions.long_entry_price
                    # 새로운 총 가치 = 기존 총 가치 + 추가 매수 가치
                    new_total_value = old_total_value + (quantity * current_price)
                    # 새로운 총 수량
                    new_total_amount = self.positions.long_amount + quantity

                    # 평균 단가와 총 수량 업데이트
                    self.positions.long_entry_price = new_total_value / new_total_amount
                    self.positions.long_amount = new_total_amount
                    logger.info(f"Position added. New total quantity: {new_total_amount:.4f}, New average entry price: {self.positions.long_entry_price:.4f}")
                else:
                    # 첫 진입 시 초기화
                    self.positions.long = current_price
                    self.positions.long_amount = quantity
                    self.positions.long_entry_price = Decimal(str(current_price))

                sl_price = Decimal(str(sl_price))
                if position in [PositionSide.LONG] and sl_price < self.positions.long_entry_price:
                    # 기존 손절매 주문이 있다면 취소
                    if self.positions.long_stop_loss_order_id:
                        self.trading_manager.cancel_order(
                            symbol=self.symbol,
                            order_id=self.positions.long_stop_loss_order_id
                        )
                    order_id = self.create_stop_market(
                        position=position,
                        symbol=self.symbol,
                        quantity=self.positions.long_amount, # 업데이트된 총 수량 사용
                        sl_price=sl_price
                        )
                    if order_id:
                        self.positions.long_stop_loss = sl_price
                        self.positions.long_stop_loss_order_id = order_id
                        logger.info(f"New stop-loss order placed with updated quantity and price.")

        except BinanceClientException as e:
            logger.error(f"FATAL: Order submission failed after all retries. Error: {e}")
            order_status_verified = self._verify_order_and_state()
            if order_status_verified:
                logger.info("CONFIRMATION: Order may have been partially filled or is pending. Check Binance for details.")
            else:
                logger.error("CONFIRMATION: No position was opened and no open orders found. The order failed completely. A new order will be attempted on the next signal.")
        except BinanceAPIException as e:
            if e.code == MARGIN_INSUFFICIENT_CODE:
                logger.critical(f"FATAL ERROR: Insufficient funds to create a {position} position. (Error code: {e.code})", exc_info=True)
            else:
                logger.error(f"Failed to open {position} position: {e.message} (Error code: {e.code})", exc_info=True)
            raise e

    def create_sell_position(self, position: PositionSide, symbol: str, quantity: Decimal):
        if position not in [PositionSide.LONG]:
            raise ValueError(f'Invalid value: {position}')
        if position in [PositionSide.LONG]:
            side = OrderSide.SELL
        try:
            order = self.trading_manager.create_market_order(
                symbol=symbol,
                side=side,
                positionSide=position,
                quantity=quantity
            )
            return order

        except BinanceAPIException as e:
            logger.error(f"Failed to close {position} position: {e.message} (Error code: {e.code})", exc_info=True)
  
    def create_stop_market(self, position: PositionSide, symbol: str, quantity: Decimal, sl_price):

        if position not in [PositionSide.LONG]:
            raise ValueError(f'Invalid value: {position}')
        
        if position == PositionSide.LONG:
            side = OrderSide.SELL
        elif position in [PositionSide.LONG]:
            side = OrderSide.BUY
        try:
            order = self.trading_manager.create_stop_market_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                stop_price=sl_price,
                positionSide=position,
            )
            return order.get('orderId', None)

        except BinanceAPIException as e:
            logger.error(f"Failed to stop markey {position} position: {e.message} (Error code: {e.code})", exc_info=True)

    def pullback_execute_long_trade(self, long_signal, low: Decimal, close: Decimal):

        if self.positions.long is not None and long_signal in [LongSignal.OPEN_POSITION, LongSignal.CLOSE_POSITION, LongSignal.SCALING_OUT]:

            if self.positions.long_stop_loss_order_id:
                try:
                    self.trading_manager.cancel_order(
                        symbol=self.symbol,
                        order_id=self.positions.long_stop_loss_order_id
                    )
                    sl_price = self.positions.long_stop_loss
                    self.positions.long_stop_loss = None
                    self.positions.long_stop_loss_order_id = None
                except BinanceAPIException as e:
                    logger.error(f"Failed to cancel order: {e.message} (Error code: {e.code})", exc_info=True)

            # if long_signal in [LongSignal.SCALING_OUT]:
            #     half_quantity = self.positions.long_amount / 3
            #     logger.info(f"SIGNAL: LONG_SCALING_OUT, Closing long half position")
            #     try:
            #         # 2. 포지션 일부 매도
            #         # 수량을 바이낸스 정밀도에 맞게 조정
            #         adjusted_half_quantity = self._adjust_quantity_by_precision(
            #             symbol=self.symbol,
            #             quantity=half_quantity
            #         )
            #         self.create_sell_position(
            #             position='LONG',
            #             symbol=self.symbol,
            #             quantity=adjusted_half_quantity
            #         )
            #         # 3. 남은 수량으로 상태 업데이트
            #         self.positions.long_amount -= adjusted_half_quantity
            #         remaining_half_quantity = self._adjust_quantity_by_precision(
            #             symbol=self.symbol,
            #             quantity=self.positions.long_amount
            #         )
            #         self.positions.long_amount = remaining_half_quantity

            #         # 손익분기점
            #         if self.positions.long_entry_price is None:
            #             logger.error("Entry price is None")
            #             return

            #         # 4. 남은 수량에 대한 새로운 손절매 주문 생성
            #         if self.positions.long_amount > 0:
            #             sl_price = self.positions.long_entry_price # <- 수정된 부분
            #             if sl_price is None:
            #                 logger.error("Could not create a new stop-loss order because there is no existing stop-loss price.")
            #                 return
            #             order_id = self.create_stop_market(
            #                 position='LONG',
            #                 symbol=self.symbol,
            #                 quantity=self.positions.long_amount,
            #                 sl_price=sl_price
            #                 )
            #             if order_id:
            #                 self.positions.long_stop_loss = sl_price
            #                 self.positions.long_stop_loss_order_id = order_id
            #                 logger.info(f"Successfully created a new stop-loss order. amount: {self.positions.long_amount}, price: {sl_price}")
            #             else:
            #                 logger.error("Failed to create a new stop-loss order.")

            #         logger.info(f"Half of the long position has been closed. Remaining quantity: {self.positions.long_amount}")

            #     except Exception as e:
            #         logger.error(f"An error occurred while closing half of the long position: {e}", exc_info=True)
            if long_signal == LongSignal.CLOSE_POSITION:
                logger.info(f"SIGNAL: {long_signal}, Closing long all position")
                try:
                    self.create_sell_position(
                        position=PositionSide.LONG,
                        symbol=self.symbol,
                        quantity=self.positions.long_amount
                    )
                    self.positions.long = None
                    self.positions.long_amount = None
                    self.positions.long_entry_price = None
                    logger.info("All long positions have been sold and the state has been reset.")
                except Exception as e:
                    logger.error(f"An error occurred while selling all long positions: {e}", exc_info=True)

        # OPEN POSTION
        if self.positions.long is None and long_signal == LongSignal.OPEN_POSITION:
            # 1. 리스크 관리 기반 수량 계산
            result = self.get_position_quantity(price=close, stop_loss_price=low)
            if len(result) == 2:
                quantity, sl_price = result
            else:
                quantity = result
                sl_price = low
            logger.info(f"SIGNAL: Pullback generated a long position entry signal! Order quantity: {quantity:.4f}")
            self.create_buy_position(position=PositionSide.LONG, quantity=quantity, current_price=close, sl_price=sl_price)