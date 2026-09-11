# -*- coding: utf-8 -*-
"""10.0优化：重绘《问题分析总体流程图》。

要求：
 1) 每一个块内文字不超过 6 个字；
 2) 多分一些块，突出逻辑的流畅性；
 3) 字号更大，与论文正文（12pt）相适应。
输出 → C题/paper/figures/flow_analysis.png
（该图被 main.tex 以 0.95\\textwidth 引用）
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'code'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import config as C

C.setup_plot_style()
plt.rcParams['axes.unicode_minus'] = False

OUT = os.path.join(C.C_BASE, 'paper', 'figures', 'flow_analysis.png')
os.makedirs(os.path.dirname(OUT), exist_ok=True)

FS = 15            # 块内正文字号（比正文 12pt 更大）
FS_T = 17          # 标题字号

# ---------------- 布局坐标（ax 0-100） ----------------
hh = 9.0                                         # 块高
top_y = 90.0                                     # 顶部主线 y
head_y = 77.0                                    # 支线标题 y
body_ys = [66.0, 54.5, 43.0, 31.5]              # 支线四个小块 y
res_y = 20.0                                     # result 块 y
bot_y = 6.0                                      # 底部汇总 y
col_x = [13.0, 37.0, 61.0, 85.0]                 # 四列左边界
bw = 23.0                                        # 列块宽

fig, ax = plt.subplots(figsize=(16.0, 11.5))
ax.set_xlim(0, 100); ax.set_ylim(0, 100)
ax.axis('off')

def box(x, y, w, text, fs=FS, bold=False):
    ax.add_patch(plt.Rectangle((x, y), w, hh, facecolor='#FFFFFF',
                 edgecolor='#000000', linewidth=1.6, zorder=2))
    ax.text(x + w/2, y + hh/2, text, ha='center', va='center',
            fontsize=fs, zorder=3,
            fontweight=('bold' if bold else 'normal'))

def varrow(xc, y1, y2):
    ax.annotate('', xy=(xc, y2), xytext=(xc, y1),
                arrowprops=dict(arrowstyle='-|>', color='#000', lw=1.6),
                zorder=1)

def harrow(x1, yc, x2):
    ax.annotate('', xy=(x2, yc), xytext=(x1, yc),
                arrowprops=dict(arrowstyle='-|>', color='#000', lw=1.6),
                zorder=1)

# ==== 顶部主线：数据预处理 → 统一建模内核（内核拆成 3 个短块） ====
topw = 16.0
tx = [2.0, 31.0, 57.0, 81.0]                     # 四个顶部块左边界
box(tx[0], top_y, topw, '数据预处理', fs=FS_T, bold=True)
box(tx[1], top_y, topw, '统一内核', fs=FS, bold=True)
box(tx[2], top_y, topw, '功率·能量守恒', fs=FS)
box(tx[3], top_y, topw, '储能·三层购电', fs=FS)
for j in range(3):
    harrow(tx[j]+topw, top_y+hh/2, tx[j+1])
# 统一内核 → 四支线（从 tx[1] 中点下分）
from_cx = tx[1] + topw/2
for cx in col_x:
    varrow(from_cx, top_y, head_y + hh)  # 从顶部块底向下

# ==== 四个支线 ====
branches = [
    ('问题一·确定性', ['单日线性规划', '购电费最小', '储能低充高放', '日循环约束']),
    ('问题二·随机化', ['两阶段随机', 'CVaR 风险', '情景生成', '帕累托前沿']),
    ('问题三·滚动',   ['滚动 MPC', '计划·调整', '违约·超额罚', '时刻重算']),
    ('问题四·波动价', ['波动电价替换', '统一重算', '压力测试', '季节·风险']),
]
for ci, (head, bods) in enumerate(branches):
    cx = col_x[ci]
    box(cx, head_y, bw, head, fs=FS_T, bold=True)
    varrow(cx + bw/2, head_y, body_ys[0] + hh)
    for k in range(len(bods)):
        box(cx, body_ys[k], bw, bods[k], fs=FS)
        if k < len(bods) - 1:
            varrow(cx + bw/2, body_ys[k], body_ys[k+1] + hh)
    box(cx, res_y, bw, 'result%d' % (ci+1), fs=FS_T, bold=True)
    varrow(cx + bw/2, body_ys[-1], res_y + hh)

# ==== 底部汇总：三块并排 ====
botw = 30.0
bxs = [5.0, 35.0, 65.0]
for cx in col_x:
    # result 块 → 底部第一个块
    varrow(cx + bw/2, res_y, bot_y + hh)
boxes = ['结果·输出', '校验·对齐', '口径·对照']
for i, bx in enumerate(bxs):
    box(bx, bot_y, botw, boxes[i], fs=FS_T, bold=True)
    if i > 0:
        harrow(bxs[i-1]+botw, bot_y+hh/2, bxs[i])
# 顶部主线 → 底部（作为整体走向）
left_x = 2.0 + topw/2
varrow(left_x, top_y, bot_y)

fig.tight_layout()
fig.savefig(OUT, dpi=150, bbox_inches='tight', facecolor='white')
print('已生成', OUT)