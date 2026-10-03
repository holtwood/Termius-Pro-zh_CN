# -*- coding: utf-8 -*-
"""Termius 字体注入入口（叠加层脚本）

本文件是本 fork 唯一的 Python 定制代码，不修改上游 lang.py 的任何内容：
通过子类化 TermiusModifier，并在运行期间临时替换 lang 模块内的类引用实现注入，
因此上游对 lang.py 的更新可以直接合并，不会产生文本冲突。

用法与 lang.py 完全一致（参数解析与调度复用上游 main()）：
    python fontlang.py          # 汉化 + 字体（无参数时上游默认执行汉化）
    python fontlang.py -lk      # 汉化 + 跳过登录 + 字体
    python fontlang.py -b -l    # Beta 版汉化 + 字体

字体注入触发条件：脚本同级存在 fonts/ 目录（字体文件 + fonts.css 模板），
删除或移走 fonts/ 目录即可关闭字体功能；不需要字体的构建直接使用 lang.py。
字体注册规则来自 rules/font.txt，在 load_rules 阶段追加编译，沿用上游规则引擎。
"""
import glob
import logging
import os
import re
import shutil

import lang


class FontTermiusModifier(lang.TermiusModifier):
    """在上游修改器基础上叠加自定义字体注入"""

    @property
    def _fonts_dir(self):
        """自定义字体目录（fonts/ 目录存在即启用字体功能）"""
        return os.path.join(self._script_dir, "fonts")

    def _compile_font_rules(self):
        """读取并编译 rules/font.txt，追加到上游已编译规则列表尾部

        编译逻辑与上游 load_rules 保持一致；若上游调整 compiled_rules 的
        元组结构，此处需同步（CI 构建失败即提示）。
        """
        rules_path = os.path.join(self._rules_dir, "font.txt")
        if not os.path.isfile(rules_path):
            logging.warning(f"Font rules not found: {rules_path}")
            return
        try:
            for line in lang.read_file(rules_path):
                if lang.is_comment_line(line):
                    continue
                try:
                    old_val, new_val = lang.parse_replace_rule(line)
                    if lang.is_regex_pattern(old_val):
                        self.compiled_rules.append(("regex", line, re.compile(old_val[1:-1]), new_val))
                    else:
                        self.compiled_rules.append(("plain", line, old_val, new_val))
                except ValueError as e:
                    logging.warning(f"Skipping invalid font rule: {line} - {str(e)}")
                except re.error as e:
                    logging.warning(f"Regex compilation error in font rule: {line} - {str(e)}")
        except Exception as e:
            logging.error(f"Failed to load font rules: {e}")

    def apply_fonts(self):
        """注入自定义字体：复制字体文件到 ui-process/assets 并在主 CSS 追加 @font-face

        字体文件来自脚本同级 fonts/ 目录，@font-face 模板来自 fonts/fonts.css。
        幂等：CSS 中已含注入标记时自动跳过。
        """
        assets_dir = os.path.join(self._app_dir, "ui-process", "assets")
        if not os.path.isdir(assets_dir):
            logging.warning(f"ui-process/assets not found: {assets_dir}, skipping font injection")
            return

        # 1. 复制字体文件到 ui-process/assets（与官方内嵌 Nerd Font 同目录）
        copied = 0
        for fname in os.listdir(self._fonts_dir):
            if not fname.lower().endswith((".ttf", ".otf", ".woff2")):
                continue
            src = os.path.join(self._fonts_dir, fname)
            dst = os.path.join(assets_dir, fname)
            shutil.copy2(src, dst)
            logging.info(f"Copied font: {fname}")
            copied += 1
        logging.info(f"Font files copied: {copied}")

        # 2. 在主 CSS 追加 @font-face（main-*.css，含 xterm 样式特征）
        css_template = os.path.join(self._fonts_dir, "fonts.css")
        if not os.path.isfile(css_template):
            logging.warning("fonts.css template not found, skipping @font-face injection")
            return
        with open(css_template, "r", encoding="utf-8") as f:
            font_faces = f.read()

        injected = 0
        for css_file in glob.glob(os.path.join(assets_dir, "main-*.css")):
            content = lang.read_file(css_file, strip_empty=False)
            if "CodeNewRoman Nerd Font Mono" in content:
                logging.info(f"Fonts already injected in {os.path.basename(css_file)}, skipped")
                continue
            if ".xterm-viewport" not in content:
                logging.debug(f"Skipping non-terminal CSS: {os.path.basename(css_file)}")
                continue
            lang.write_file_atomic(css_file, content + "\n" + font_faces)
            logging.info(f"Injected @font-face into {os.path.basename(css_file)}")
            injected += 1
        if injected == 0:
            logging.warning("No suitable main-*.css found for @font-face injection")
        else:
            logging.info(f"@font-face injected into {injected} CSS file(s)")

    def load_rules(self):
        """上游规则加载完成后，追加编译字体规则并执行字体文件注入

        load_rules 在上游流程中位于解压之后、替换与打包之前，
        正好覆盖字体注入的两个需求：注册规则进引擎、字体文件进资源目录。
        """
        super().load_rules()
        if not os.path.isdir(self._fonts_dir):
            logging.info("fonts/ directory not found, font injection disabled")
            return
        self._compile_font_rules()
        self.apply_fonts()


def main():
    """复用上游 lang.main 的参数解析与调度，仅把修改器替换为字体增强版

    上游 main() 按模块全局名构造 TermiusModifier，运行期间临时替换该名字即可，
    上游 argparse 或调度流程的变更无需在本文件同步维护。
    """
    original = lang.TermiusModifier
    lang.TermiusModifier = FontTermiusModifier
    try:
        lang.main()
    finally:
        lang.TermiusModifier = original


if __name__ == "__main__":
    main()
