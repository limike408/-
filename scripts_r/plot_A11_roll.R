# scripts_r/plot_A11_roll.R —— A11 问题三：仅0:00 vs 滚动 总费用结构（四日堆叠柱）
# 数据：report/q3_rolling_comparison.csv（code/main_q3.py analysis 生成）
# 输出：paper/figures_adv/A11_q3_roll_compare.png 与 report/figures_adv/ 同名

source("scripts_r/theme_zh.R")
suppressMessages(library(dplyr))
suppressMessages(library(tidyr))

d <- read.csv("report/q3_rolling_comparison.csv", stringsAsFactors = FALSE)
daylab <- c("2025-03-20" = "03-20", "2025-06-21" = "06-21",
            "2025-09-23" = "09-23", "2025-12-21" = "12-21")
d <- d %>% mutate(day = factor(daylab[day], levels = unname(daylab)))

long <- bind_rows(
  d %>% transmute(day, grp = "仅 0:00", grid = only0_grid / 1e4, emer = only0_emerg / 1e4,
                  tot = only0_total / 1e4),
  d %>% transmute(day, grp = "0/6/12/18 滚动", grid = roll_grid / 1e4, emer = roll_emerg / 1e4,
                  tot = roll_total / 1e4)
) %>% mutate(grp = factor(grp, levels = c("仅 0:00", "0/6/12/18 滚动")))

p <- ggplot(long, aes(x = grp)) +
  geom_col(aes(y = grid, fill = "电网费"), width = 0.62) +
  geom_col(aes(y = tot, fill = "紧急购电费"), width = 0.62) +
  geom_text(aes(y = tot + 0.08, label = sprintf("%.1f", tot)),
            family = ZHFAM, size = 3.6) +
  facet_wrap(~ day, nrow = 1) +
  scale_fill_manual(values = c("电网费" = "#4C72B0", "紧急购电费" = "#C44E52")) +
  labs(title = "问题三：引入多时刻预报前后总费用对比（堆叠柱）",
       x = NULL, y = "费用（万元）", fill = NULL) +
  scale_y_continuous(expand = expansion(mult = c(0, 0.08)), limits = c(0, NA)) +
  theme_paper(12) +
  theme(axis.text.x = element_text(angle = 0, size = 10))

for (out in c("paper/figures_adv/A11_q3_roll_compare.png",
              "report/figures_adv/A11_q3_roll_compare.png")) {
  ggsave(out, p, width = 9.5, height = 5.2, dpi = 150)
}
cat("已生成 A11_q3_roll_compare.png\n")
print(long)
