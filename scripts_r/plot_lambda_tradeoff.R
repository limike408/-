# scripts_r/plot_lambda_tradeoff.R —— Q2 全年 λ 权衡曲线（新图 fig:lambdatradeoff）
# 数据：report/q2_lambda_sweep.csv（code/q2_lambda_sweep.py 生成）
# 输出：paper/figures_adv/q2_lambda_tradeoff.png 与 report/figures_adv/ 同名
# 用法：Rscript scripts_r/plot_lambda_tradeoff.R [lambda_star]

args <- commandArgs(trailingOnly = TRUE)
lam_star <- if (length(args) >= 1) as.numeric(args[1]) else 1.0
source("scripts_r/theme_zh.R")
suppressMessages(library(dplyr))

d <- read.csv("report/q2_lambda_sweep.csv")
d$total <- d$plan_fee + d$emerg_fee

p <- ggplot(d, aes(x = lam)) +
  geom_line(aes(y = plan_fee / 1e4), colour = "#0072B2", linewidth = 1.0) +
  geom_point(aes(y = plan_fee / 1e4), colour = "#0072B2", size = 2.2) +
  geom_line(aes(y = emerg_fee / 1e4), colour = "#C44E52", linewidth = 1.0) +
  geom_point(aes(y = emerg_fee / 1e4), colour = "#C44E52", size = 2.2) +
  geom_line(aes(y = total / 1e4), colour = "#333333", linewidth = 1.0, linetype = "dashed") +
  geom_point(aes(y = total / 1e4), colour = "#333333", size = 2.2, shape = 17) +
  geom_vline(xintercept = lam_star, colour = "#D55E00", linetype = "dotted", linewidth = 1.1) +
  annotate("text", x = lam_star + 0.12, y = max(d$total / 1e4) * 0.99,
           label = sprintf("官方 λ* = %g", lam_star),
           colour = "#D55E00", hjust = 0, family = ZHFAM, size = 4.2) +
  scale_x_continuous(breaks = unique(d$lam)) +
  labs(title = "问题二：CVaR 风险权重 λ 的全年权衡曲线（2.1–12.31）",
       x = "风险权重 λ", y = "全年费用（万元）") +
  annotate("text", x = max(d$lam), y = d$plan_fee[nrow(d)] / 1e4, label = "计划购电费",
           hjust = 1, vjust = -1, colour = "#0072B2", family = ZHFAM, size = 4) +
  annotate("text", x = max(d$lam), y = d$emerg_fee[nrow(d)] / 1e4, label = "紧急购电费",
           hjust = 1, vjust = 1.6, colour = "#C44E52", family = ZHFAM, size = 4) +
  annotate("text", x = max(d$lam), y = d$total[nrow(d)] / 1e4, label = "合计",
           hjust = 1, vjust = 2.4, colour = "#333333", family = ZHFAM, size = 4) +
  theme_paper(12)

for (out in c("paper/figures_adv/q2_lambda_tradeoff.png",
              "report/figures_adv/q2_lambda_tradeoff.png")) {
  ggsave(out, p, width = 8.6, height = 5.2, dpi = 200)
}
cat("已生成 q2_lambda_tradeoff.png (λ* =", lam_star, ")\n")
print(round(d, 2))
