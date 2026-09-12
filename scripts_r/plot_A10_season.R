# scripts_r/plot_A10_season.R —— A10 问题四：季节日均费用 固定/波动 对比 + 上浮百分比
# 数据：report/season_cost_split.csv（code/season_split.py 生成，Q3 口径）
# 输出：paper/figures_adv/A10_season_cost.png 与 report/figures_adv/ 同名

source("scripts_r/theme_zh.R")
suppressMessages(library(dplyr))
suppressMessages(library(tidyr))

d <- read.csv("report/season_cost_split.csv", stringsAsFactors = FALSE)
d$seas <- factor(d$seas, levels = d$seas)

long <- d %>%
  select(seas, q3_fix, q3_var, up3) %>%
  pivot_longer(c(q3_fix, q3_var), names_to = "grp", values_to = "val") %>%
  mutate(grp = factor(ifelse(grp == "q3_fix", "固定电价", "波动电价"),
                      levels = c("固定电价", "波动电价")))

p <- ggplot(long, aes(x = seas, y = val, fill = grp)) +
  geom_col(position = position_dodge(0.7), width = 0.6) +
  geom_text(aes(label = sprintf("%.2f", val)),
            position = position_dodge(0.7), vjust = -0.4,
            family = ZHFAM, size = 3.4) +
  geom_text(data = d, aes(x = seas, y = pmax(q3_fix, q3_var) + 0.4,
                          label = sprintf("+%.1f%%", up3)),
            inherit.aes = FALSE, colour = "#C44E52", family = ZHFAM, size = 3.8) +
  scale_fill_manual(values = c("固定电价" = "#4C72B0", "波动电价" = "#DD8452")) +
  labs(title = "问题四：波动电价下季节日均费用的季节性差异（问题三）",
       x = "季节", y = "日均费用（万元/日）", fill = NULL) +
  scale_y_continuous(expand = expansion(mult = c(0, 0.12)), limits = c(0, NA)) +
  theme_paper(12)

for (out in c("paper/figures_adv/A10_season_cost.png",
              "report/figures_adv/A10_season_cost.png")) {
  ggsave(out, p, width = 8.5, height = 5.0, dpi = 150)
}
cat("已生成 A10_season_cost.png\n")
print(d)
