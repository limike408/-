# scripts_r/theme_zh.R —— R 绘图公共主题（ggplot2 + 中文字体）
# 用法：source("theme_zh.R") 后直接使用 theme_paper() 与 ZHFAM。

suppressMessages({
  library(ggplot2)
  library(showtext)
  library(sysfonts)
})

# 中文字体：优先项目内楷体，其次系统黑体/宋体
font_files <- c(
  simkai = "paper/simkai.ttf",
  msyh   = "C:/Windows/Fonts/msyh.ttc",
  simhei = "C:/Windows/Fonts/simhei.ttf",
  simsun = "C:/Windows/Fonts/simsun.ttc"
)
ZHFAM <- "sans"
for (nm in names(font_files)) {
  if (file.exists(font_files[[nm]])) {
    font_add(nm, font_files[[nm]])
    ZHFAM <- nm
    break
  }
}
showtext_auto()

# 论文统一主题：白底、浅灰网格、统一字号（与 Python 侧 matplotlib 风格协调）
theme_paper <- function(base = 12) {
  theme_bw(base_size = base) +
    theme(
      text = element_text(family = ZHFAM),
      plot.title = element_text(size = base + 1, face = "bold", hjust = 0.5),
      axis.title = element_text(size = base),
      axis.text = element_text(size = base - 1),
      legend.text = element_text(size = base - 1),
      legend.title = element_text(size = base - 1),
      panel.grid.minor = element_blank(),
      panel.grid.major = element_line(colour = "#dddddd", linewidth = 0.3),
      legend.background = element_blank()
    )
}
