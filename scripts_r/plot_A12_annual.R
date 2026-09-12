# scripts_r/plot_A12_annual.R —— A12 全年费用结构：Q2 / Q3 / Q4-3（电网费 vs 紧急购电费 堆叠）
# 数据：report/plot_annual.csv（code/export_plot_data.py 从结果附件汇总）
# 输出：paper/figures_adv/A12_annual_cost.png 与 report/figures_adv/ 同名

source("scripts_r/theme_zh.R")
suppressMessages(library(dplyr))

d <- read.csv("report/plot_annual.csv", stringsAsFactors = FALSE)
d <- d %>%
  mutate(label = gsub("\\\\n", "\n", label),
         label = factor(label, levels = label),
         total = grid_fee + emerg_fee)

p <- ggplot(d, aes(x = label)) +
  geom_col(aes(y = grid_fee / 1e6), fill = "#4C72B0", width = 0.5) +
  geom_col(aes(y = emerg_fee / 1e6), fill = "#C44E52", width = 0.5) +
  geom_text(aes(y = total / 1e6 + 0.35, label = sprintf("%.0f 万元", total / 1e4)),
            family = ZHFAM, size = 4.2) +
  geom_text(aes(y = (grid_fee + emerg_fee / 2) / 1e6,
                label = ifelse(emerg_fee > 1e5, sprintf("%.0f 万元", emerg_fee / 1e4), "")),
            colour = "white", family = ZHFAM, size = 3.8) +
  labs(title = "全年费用结构：随机/滚动模型逐步逼近真实成本的对比",
       x = NULL, y = "费用（百万元）") +
  scale_y_continuous(expand = expansion(mult = c(0, 0.08)), limits = c(0, NA)) +
  theme_paper(12)

for (out in c("paper/figures_adv/A12_annual_cost.png",
              "report/figures_adv/A12_annual_cost.png")) {
  ggsave(out, p, width = 8.5, height = 5.0, dpi = 150)
}
cat("已生成 A12_annual_cost.png\n")
print(d)
