# -*- coding: utf-8 -*-
"""C题 微网 —— 共享配置。所有路径/代数、储能参数、结果模板统一放工作区仓库内。"""
import os

# ---- 路径（相对仓库根自动定位，任何机器 clone 后直接可跑）----
C_BASE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(C_BASE, 'data')
TPL_DIR  = os.path.join(DATA_DIR, '附件5模板')
CODE_DIR = os.path.join(C_BASE, 'code')
RES_DIR  = os.path.join(C_BASE, 'report')
FIG_DIR  = os.path.join(C_BASE, 'report', 'figures')
for _d in (RES_DIR, FIG_DIR):
    os.makedirs(_d, exist_ok=True)

# matplotlib 缓存等中间数据也放仓库内，不污染系统目录
os.environ['MPLCONFIGDIR'] = os.path.join(C_BASE, '_mplcache')
os.makedirs(os.environ['MPLCONFIGDIR'], exist_ok=True)

def setup_plot_style():
    """注册本机中文字体（只读取系统字体文件，不写 C 盘）。"""
    import matplotlib
    from matplotlib import font_manager
    cands = [r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\msyh.ttf',
             r'C:\Windows\Fonts\simhei.ttf', r'C:\Windows\Fonts\simsun.ttc',
             r'C:\Windows\Fonts\simkai.ttf']
    names = []
    for f in cands:
        try:
            if os.path.exists(f):
                fp = font_manager.FontProperties(fname=f)
                names.append(fp.get_name())
                font_manager.fontManager.addfont(f)
        except Exception:
            pass
    mpl = matplotlib
    mpl.rcParams['font.sans-serif'] = names + ['DejaVu Sans']
    mpl.rcParams['axes.unicode_minus'] = False
    # 21.0：全局调大默认字号（脚本内显式 fontsize 仍优先）
    mpl.rcParams['font.size'] = 12
    mpl.rcParams['axes.labelsize'] = 13
    mpl.rcParams['axes.titlesize'] = 14
    mpl.rcParams['xtick.labelsize'] = 12
    mpl.rcParams['ytick.labelsize'] = 12
    mpl.rcParams['legend.fontsize'] = 12

# ---- 时间离散 ----
T_IN_DAY = 144           # 每天 10 分钟时段数
DT = 1.0 / 6.0           # 每时段时长 (h)；功率 kW * DT = 能量 kWh
DAYS_OUT_START = 32      # 2.1 对应的行偏移（日期数组从 1.1 起，行索引0=1.1）

# ---- 储能参数（附录1）----
SOC_MAX = 12000.0        # kWh
SOC_MIN = 1200.0
SOC_HIGH_BOUND = 10800.0 # 实际运行上界（附录1：保持 1200-10800）
PWR_MAX = 5000.0         # kW
E_CMAX = PWR_MAX * DT    # 每时段最大充入能量 kWh = 833.33
E_FMAX = PWR_MAX * DT
ETA = 0.9                # 充/放电效率
E_INIT = 6000.0          # 2025-1-1 0:00 储电量

# ---- 电价机制 ----
EMERG_MULT = 5.0         # 紧急购电 = 交易时刻电价 5 倍
DEFAULT_MULT = 0.5       # 计划高于调整(少购)部分按 50% 违约价
EXCESS_MULT = 1.5        # 调整高于计划(多购)部分按 1.5 倍

# ---- 时间标签 ----
def interval_label(t0):
    start_min = t0 * 10
    end_min = start_min + 10
    h1, m1 = divmod(start_min, 60)
    h2, m2 = divmod(end_min, 60)
    return f'{h1}:{m1:02d}-{h2}:{m2:02d}'

INTERVAL_LABELS = [interval_label(t0) for t0 in range(T_IN_DAY)]

BLOCK4 = [(0, '0:00-4:00'), (4, '4:00-8:00'), (8, '8:00-12:00'),
          (12, '12:00-16:00'), (16, '16:00-20:00'), (20, '20:00-24:00')]

# 表1 指定时段（起始分钟）
SPEC_MINUTES = [600, 720, 840, 960, 1080, 1200]

# ---- 随机规划参数 ----
S_NUM = 30            # 情景数
BETA = 0.90           # CVaR 置信水平
SPEC_DAYS = ['2025-03-20', '2025-06-21', '2025-09-23', '2025-12-21']