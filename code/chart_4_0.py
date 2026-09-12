# -*- coding: utf-8 -*-
"""【已迁移】A9-A12 四张图的生成已迁移至 R（ggplot2），本文件不再生成图表。

原因：15.0 之后的重绘环节按"清晰直观"标准做工具选型，A9（λ 对比堆叠柱）、
A10（季节费用对比）、A11（Q3 滚动对比）、A12（全年费用结构）改用 R 绘制：
  - scripts_r/plot_A9_cvar.R       →  paper/figures_adv/A9_q2_cvar_compare.png
  - scripts_r/plot_A10_season.R    →  paper/figures_adv/A10_season_cost.png
  - scripts_r/plot_A11_roll.R      →  paper/figures_adv/A11_q3_roll_compare.png
  - scripts_r/plot_A12_annual.R    →  paper/figures_adv/A12_annual_cost.png
数据依赖：report/q2_two_stage_comparison.csv、report/season_cost_split.csv、
          report/q3_rolling_comparison.csv、report/plot_annual.csv。
请勿再运行本文件（历史版本可查 git 记录：12.0优化 分支）。
"""
import os, sys

if __name__ == '__main__':
    print('A9-A12 已迁移至 scripts_r/（R/ggplot2），请运行对应 R 脚本。')
