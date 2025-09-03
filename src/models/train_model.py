import pandas as pd
import numpy as np
import pandas_ta as ta
from binance.client import Client
from sklearn.preprocessing import MinMaxScaler
from tensorflow.keras.callbacks import EarlyStopping
from joblib import dump, load # 파일 입출력을 위한 라이브러리 추가
# 날짜 계산을 위한 datetime 모듈 임포트
from datetime import datetime, timedelta
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout, Bidirectional, Conv1D, MaxPooling1D, Flatten
from tensorflow.keras.optimizers import Adam # 추가된 부분

LEARNING_RATE = 0.0001 # 0.0001을 기준으로 0.001, 0.0005 또는 0.00005, 0.00001 등으로 변경
BATCH_SIZE = 128 # 64, 128, 256, 512
DROPOUT_RATE = 0.2 # 0.2 기준 0.1 ~ 0.5 과적합되는 경향이 보이면 값을 높이고, 학습이 잘 안 되는 것 같으면 값을 낮춰보세요.

# API 키 및 시크릿 키 설정 (자신의 키로 대체)
api_key = "zjzU5ebopzUHq0sARTfOdfvcDSS2CJZRLzDSXCItM3N3xBTBo56NtJUqt6ahXlmZ"
api_secret = "CyLplruf7yF1car5G8TGqQjxAdRzv7bClZC95fy4b44i5Ljk8TskzX5sN4ZBSpTd"

# 클라이언트 생성
client = Client(api_key, api_secret)

years_to_fetch = 3
start_date = datetime.now() - timedelta(days=365 * years_to_fetch)
# 바이낸스 API가 요구하는 형식('1 Jan, 2020')으로 변환
start_date_str = start_date.strftime("%d %b, %Y")

print(f"시작 날짜: {start_date_str}")

# 과거 데이터 가져오기
candles = client.get_historical_klines("XRPUSDT", Client.KLINE_INTERVAL_5MINUTE, "1 Jan, 2024")

# DataFrame으로 변환
df = pd.DataFrame(candles, columns=['Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close time', 'Quote asset volume', 'Number of trades', 'Taker buy base asset volume', 'Taker buy quote asset volume', 'Ignore'])
df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
df = df.apply(pd.to_numeric)

# ADX 계산
df['ADX'] = ta.adx(df['High'], df['Low'], df['Close'], length=14)['ADX_14']

# 볼린저 밴드 너비 계산
bbands = ta.bbands(df['Close'], length=20, std=2.0)
df['BBD'] = bbands['BBP_20_2.0']

# 결측값(NaN) 제거
df.dropna(inplace=True)

# 횡보장과 추세장 라벨링
df['label'] = np.where(df['ADX'] > 25, 1, 0)

# --- 여기부터 수정된 부분입니다 ---

# 1. 시계열 순서대로 데이터 분할 (train_test_split 대신 직접 분할)
# 전체 데이터의 80%를 훈련용으로, 20%를 테스트용으로 사용
train_size = int(len(df) * 0.8)
train_df = df[:train_size]
test_df = df[train_size:]

# 훈련 및 테스트 데이터에서 특징과 라벨 분리
train_features = train_df[['Open', 'High', 'Low', 'Close', 'Volume', 'ADX', 'BBD']].values
train_labels = train_df['label'].values
test_features = test_df[['Open', 'High', 'Low', 'Close', 'Volume', 'ADX', 'BBD']].values
test_labels = test_df['label'].values

# 2. 훈련 데이터에만 스케일러를 맞추기 (fit)
scaler = MinMaxScaler(feature_range=(0, 1))
scaler.fit(train_features)

# 3. 훈련 및 테스트 데이터 모두 변환 (transform)
scaled_train_features = scaler.transform(train_features)
scaled_test_features = scaler.transform(test_features)

# 4. 각 데이터셋에 대해 시퀀스 생성
sequence_length = 60

def create_sequences(data, labels, seq_length):
    X, y = [], []
    for i in range(len(data) - seq_length):
        X.append(data[i:i + seq_length])
        y.append(labels[i + seq_length])
    return np.array(X), np.array(y)

X_train, y_train = create_sequences(scaled_train_features, train_labels, sequence_length)
X_test, y_test = create_sequences(scaled_test_features, test_labels, sequence_length)

# --- 여기까지 수정된 부분입니다 ---

# LSTM 모델 구축
model = Sequential()

# CNN 레이어 추가
# filters: 컨볼루션 필터의 수. 32개 필터로 특징을 추출합니다.
# kernel_size: 컨볼루션 윈도우의 크기. 3개의 타임스텝을 묶어 패턴을 찾습니다.
model.add(Conv1D(filters=32, kernel_size=3, activation='relu', input_shape=(X_train.shape[1], X_train.shape[2])))
model.add(MaxPooling1D(pool_size=2))
model.add(Dropout(DROPOUT_RATE))

# CNN 출력에 맞춰 LSTM 레이어의 입력 형태를 조정합니다.
# 첫 번째 양방향 LSTM 레이어
model.add(Bidirectional(LSTM(100, return_sequences=True)))
model.add(Dropout(DROPOUT_RATE))
# 두 번째 양방향 LSTM 레이어 (Stacked 구조)
model.add(Bidirectional(LSTM(50, return_sequences=True)))
model.add(Dropout(DROPOUT_RATE))
# 마지막 양방향 LSTM 레이어
model.add(Bidirectional(LSTM(50)))
model.add(Dropout(DROPOUT_RATE))

# Flatten 레이어를 추가하여 CNN의 3D 출력을 LSTM의 2D 입력에 맞게 변환합니다.
model.add(Flatten())

model.add(Dense(1, activation='sigmoid')) # 이진 분류이므로 sigmoid 활성화 함수 사용

# 모델 컴파일
# Learning Rate를 0.0001로 조정
optimizer = Adam(learning_rate=LEARNING_RATE)
model.compile(optimizer=optimizer, loss='binary_crossentropy', metrics=['accuracy'])

# 조기 종료 콜백 설정: `val_loss`가 5 에폭 동안 개선되지 않으면 학습을 중단하고 최적의 가중치를 복원합니다.
early_stopping = EarlyStopping(monitor='val_loss', patience=5, restore_best_weights=True)

# 모델 학습
history = model.fit(X_train, y_train, epochs=100, batch_size=BATCH_SIZE, validation_data=(X_test, y_test), callbacks=[early_stopping], verbose=1)

# 모델 평가
loss, accuracy = model.evaluate(X_test, y_test)
print(f"모델 정확도: {accuracy*100:.2f}%")

# 학습이 완료된 모델과 스케일러를 파일로 저장
model.save('src/models/trend_model.h5')
dump(scaler, 'src/models/scaler.joblib')
print("모델과 스케일러가 성공적으로 저장되었습니다.")