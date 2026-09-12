# scripts_r/plot_A9_cvar.R —— A9 问题二方法层：λ=0 vs λ=λ* 的"计划费换可靠性"堆叠柱
# 数据：report/q2_two_stage_comparison.csv（code/main_q2.py method_analysis 生成）
# 输出：paper/figures_adv/A9_q2_cvar_compare.png 与 report/figures_adv/ 同名
# 用法：Rscript scripts_r/plot_A9_cvar.R [lambda_star]

args <- commandArgs(trailingOnly = TRUE)
lam_star <- if (length(args) >= 1) as.numeric(args[1]) else 1.0
source("scripts_r/theme_zh.R")
suppressMessages(library(dplyr))

d <- read.csv("report/q2_two_stage_comparison.csv", stringsAsFactors = FALSE)
d <- d %>% filter(lam %in% c(0.0, lam_star))
daylab <- c("2025-03-20" = "03-20", "2025-06-21" = "06-21",
            "2025-09-23" = "09-23", "2025-12-21" = "12-21")
d <- d %>% mutate(day = factor(daylab[day], levels = unname(daylab)),
                  lam_lab = factor(sprintf("λ=%g", lam),
                                   levels = c("λ=0", sprintf("λ=%g", lam_star))))

d <- d %>% mutate(emerg_fee = total - plan_fee)
p <- ggplot(d, aes(x = lam_lab)) +
  geom_col(aes(y = plan_fee / 1e4, fill = "计划购电费"), width = 0.62) +
  geom_col(aes(y = emerg_fee / 1e4, fill = "紧急购电费"), width = 0.62) +
  geom_text(aes(y = total / 1e4 + 0.12, label = sprintf("%.1f", total / 1e4)),
            family = ZHFAM, size = 3.6) +
  facet_wrap(~ day, nrow = 1) +
  scale_fill_manual(values = c("计划购电费" = "#4C72B0", "紧急购电费" = "#C44E52")) +
  labs(title = "问题二方法层：风险权重 λ 下\"计划费换可靠性\"权衡（堆叠柱）",
       x = NULL, y = "费用（万元）", fill = NULL) +
  scale_y_continuous(expand = expansion(mult = c(0, 0.08)), limits = c(0, NA)) +
  theme_paper(12)

for (out in c("paper/figures_adv/A9_q2_cvar_compare.png",
              "report/figures_adv/A9_q2_cvar_compare.png")) {
  ggsave(out, p, width = 9.5, height = 5.2, dpi = 150)
}
cat("已生成 A9_q2_cvar_compare.png (λ=0 vs λ*=", lam_star, ")\n")
print(d)
