import matplotlib.pyplot as plt
import logging
from typing import List
from decimal import Decimal
import numpy as np 
import matplotlib
matplotlib.use('Agg')
from datetime import datetime
import os 

logger = logging.getLogger("RENDERER")

def plot_line_chart(all_data: List[List[Decimal]], line_labels: List[str], main_title: str, filename: str) -> None:
    """
    Decimal 리스트의 리스트를 받아 선 차트를 생성하고 PNG 파일로 저장합니다.
    - 모든 차트에 범례를 표시합니다.
    - 각 서브플롯 위에 제목을 표시하지 않습니다.
    - 인덱스 0번 지표는 라인 없이 영역 채우기만 표시합니다.
    - 모든 지표는 중첩하지 않고 각각 별도의 서브플롯에 표시합니다. (원래대로 복구)
    """
    if not all_data or not all_data[0]:
        logger.warning(f"Cannot plot chart: data list is empty for {main_title}.")
        return

    if len(all_data) != len(line_labels):
        logger.error("The number of data lists and the number of labels do not match.")
        return
        
    num_total_data = len(all_data)
    
    # 중첩하지 않으므로, 그려질 차트의 개수는 전체 지표의 개수와 같습니다.
    num_charts = num_total_data 
    
    # 지표에 사용할 색상 리스트
    colors = ['white', 'black', 'green', 'red', 'purple', 'blue', 'magenta', 'orange'] 

    try:
        # 서브플롯 생성: constrained_layout 제거하고 수동 레이아웃 조정 적용
        fig, axes = plt.subplots(nrows=num_charts, ncols=1, figsize=(12, 2 * num_charts), constrained_layout=True)

        if num_charts == 1:
            axes = [axes]

        fig.suptitle(main_title, fontsize=16) # , y=0.998

        # 서브플롯에 할당할 인덱스 (axes 리스트의 인덱스)
        ax_index = 0
        
        # 모든 지표를 순회하며 차트 생성
        for i in range(num_total_data):

            data = all_data[i]
            label = line_labels[i]
            ax = axes[ax_index]
            
            plot_data = np.array([float(d) for d in data])
            
            # --- 0번 인덱스(첫 번째 지표) 특수 처리: 영역 채우기 ---
            if i == 0:
                # 양/음수 영역 채우기 
                ax.fill_between(range(len(plot_data)), plot_data, 0, 
                                where=(plot_data >= 0), 
                                facecolor='green', alpha=0.5,
                                interpolate=True)
                
                ax.fill_between(range(len(plot_data)), plot_data, 0, 
                                where=(plot_data <= 0), 
                                facecolor='red', alpha=0.5,
                                interpolate=True)
                
                # 범례를 위해 투명한 라인을 대신 추가
                ax.set_title(label, fontsize=12, loc='left')
    
                # *** 이 부분을 수정합니다: 차트 왼쪽 아래 (-0.05, 0) 외부에 배치 ***
                ax.legend(loc='lower left', bbox_to_anchor=(-0.05, 0), fontsize=10, framealpha=0) 

            # --- 0번이 아닌 일반적인 지표 처리 (2, 4번 포함) ---
            else:
                color = colors[i % len(colors)]
                
                # 라인 그리기
                ax.plot(plot_data, color=color, linewidth=2, label=label)

                # 범례 추가 
                ax.legend(loc='upper left', fontsize=10, framealpha=0)
            
            ax_index += 1

            # --- 공통 설정 ---
            ax.grid(True, linestyle='--', alpha=0.7)
            
            # Y축 눈금(Tick)을 오른쪽에 표시하도록 설정
            ax.yaxis.tick_right()
            ax.yaxis.set_label_position('right')

            # 맨 아래 차트에만 X축 라벨을 표시합니다.
            if ax_index < num_charts:
                axes[ax_index-1].tick_params(labelbottom=False)
            else:
                axes[ax_index-1].set_xlabel("", fontsize=12)
        # --- 공통 설정 끝 ---

        output_filename = filename 
        
        if not output_filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            output_filename = f"{output_filename}.png"

        plt.savefig(output_filename)
        logger.info(f"Subplot chart saved to {output_filename}")
        plt.close()

    except Exception as e:
        logger.error(f"Error while plotting subplot chart: {e}", exc_info=True)