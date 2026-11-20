"""文本流处理工具。

核心是 ThinkFilter —— 过滤掉模型输出里的 <think>...</think> 推理块。
"""

import re

#: 推理块标签。MiniMax 这类模型会把思考过程混在正文里输出。
_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


class ThinkFilter:
    """过滤掉流式输出中的 <think>...</think> 推理块。

    为什么需要它：
      MiniMax-M3 这类模型的推理内容会直接混在 content 流里，
      实测能看到 "<think>The user asks about..." 直接推给前端。

    为什么实现得这么绕：
      标签会跨 chunk 断裂，可能先来 "...<thi" 再来 "nk>..."。
      所以要把"可能是标签前缀"的尾巴扣住，等下一个 chunk 再判断。
    """

    def __init__(self) -> None:
        self._inside = False  # 当前是否在推理块内部
        self._pending = ""  # 扣住等待确认的尾巴

    def feed(self, text: str) -> str:
        """喂入一段文本，返回滤掉推理块后的净内容。"""
        buf = self._pending + text
        self._pending = ""
        out: list[str] = []
        i = 0

        while i < len(buf):
            # 在推理块内部就找结束标签，否则找开始标签
            tag = _THINK_CLOSE if self._inside else _THINK_OPEN
            idx = buf.find(tag, i)
            if idx == -1:
                # 没找到完整标签 —— 把可能是标签前缀的尾巴扣住
                tail = self._partial_tag(buf[i:], tag)
                if not self._inside:
                    # 只有在推理块外部的内容才输出
                    out.append(buf[i : len(buf) - len(tail)])
                self._pending = tail
                i = len(buf)
                continue

            if not self._inside:
                # 开始标签之前的正常内容
                out.append(buf[i:idx])
            # 遇到结束标签就出块，遇到开始标签就进块
            self._inside = not self._inside
            i = idx + len(tag)

        return "".join(out)

    def flush(self) -> str:
        """流结束时把扣住的尾巴吐出来（如果它在推理块外面）。"""
        tail = self._pending
        self._pending = ""
        return tail if not self._inside else ""

    @staticmethod
    def _partial_tag(rest: str, tag: str) -> str:
        """找出 rest 的后缀中最长的、可能是 tag 前缀的那一段。

        例如 rest="...<thi"、tag="<think>"，就返回 "<thi" 扣住。
        """
        for size in range(min(len(tag) - 1, len(rest)), 0, -1):
            if rest.endswith(tag[:size]):
                return rest[-size:]
        return ""


def strip_think(text: str) -> str:
    """一次性剥掉完整文本里的推理块（用于非流式场景）。"""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
