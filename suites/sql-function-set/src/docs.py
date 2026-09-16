from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from postgres_gym import settings

_ENTRY_RE = re.compile(r'<entry role="func_table_entry">(.*?)</entry>', re.DOTALL)

_PARA_RE = re.compile(r"<para\b([^>]*)>(.*?)</para>", re.DOTALL)
_SIGNATURE_RE = re.compile(r'<para role="func_signature">(.*?)</para>', re.DOTALL)
_PRIMARY_RE = re.compile(r"<primary>([^<]+)</primary>")
_FUNCTION_RE = re.compile(r"<function>([^<]+)</function>")
_TAG_RE = re.compile(r"<[^>]+>")

_EXAMPLE_RE = re.compile(
    r"^\s*<literal>((?:(?!</?literal>).)*)</literal>\s*"
    r"<returnvalue>(.*?)</returnvalue>", re.DOTALL)

_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL)

_TITLE_NAME_RE = re.compile(r"<(?:function|literal)>([^<]+)</(?:function|literal)>")

_SCREEN_RE = re.compile(
    r"(SELECT\b.*?;)\s*<lineannotation>[^<]*</lineannotation>\s*"
    r"<computeroutput>(.*?)</computeroutput>", re.DOTALL)
_BLOCK_RE = re.compile(
    r"<(screen|synopsis|programlisting|table|informaltable)\b.*?</\1>", re.DOTALL)

MAX_DESCRIPTION = 4000

def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub("", text)).strip()

def _tidy(text: str) -> str:
    cleaned = re.sub(r"\s*\(\s*see(\s+also)?\s*\)", "", text)
    cleaned = re.sub(r"[;,]?\s*\bsee(\s+also)?\s*(?=\.|$)", "", cleaned)

    if cleaned != text:
        cleaned = re.sub(r"\s+([.,;])", r"\1", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip()

@lru_cache(maxsize=1)
def _sgml(sgml_dir: str) -> list[tuple[str, str]]:
    out = []
    for path in sorted(Path(sgml_dir).rglob("*.sgml")):
        try:
            out.append((str(path), path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return out

def _from_table(text: str, proname: str) -> tuple[list[str], list[str]]:
    descriptions, examples = [], []

    for block in _ENTRY_RE.findall(text):
        signature = _SIGNATURE_RE.search(block)
        named = (proname in _PRIMARY_RE.findall(block)
                 or (signature is not None
                     and proname in _FUNCTION_RE.findall(signature.group(1))))
        if not named:
            continue

        for attrs, para in _PARA_RE.findall(block):
            if example := _EXAMPLE_RE.match(para):
                call, result = _plain(example.group(1)), _plain(example.group(2))
                if call.startswith(proname):
                    examples.append(f"{call} -> {result}")
                continue
            if "func_signature" in attrs:
                continue

            if plain := _tidy(_plain(para)):
                descriptions.append(plain)

    return descriptions, examples

def _section_body(text: str, title_pos: int) -> str:
    end = text.find("</sect", title_pos)
    return text[title_pos:end if end != -1 else len(text)]

def _from_section(text: str, proname: str) -> tuple[list[str], list[str]]:
    descriptions, examples = [], []

    for match in _TITLE_RE.finditer(text):
        names = [n.lower() for n in _TITLE_NAME_RE.findall(match.group(1))]
        if proname.lower() not in names:
            continue

        remainder = _plain(match.group(1))
        for name in _TITLE_NAME_RE.findall(match.group(1)):
            remainder = remainder.replace(_plain(name), "", 1)
        if remainder.strip(" ,;:/&-") :
            continue

        body = _section_body(text, match.start())
        for call, result in _SCREEN_RE.findall(body):
            call, result = _plain(call).rstrip(";"), _plain(result)
            if proname in call:
                examples.append(f"{call} -> {result}")

        prose = _BLOCK_RE.sub(" ", body)
        for _, para in _PARA_RE.findall(prose):
            if plain := _tidy(_plain(para)):
                descriptions.append(plain)

    return descriptions, examples

_SYNOPSIS_RE = re.compile(r"<synopsis>(.*?)</synopsis>", re.DOTALL)

def _from_synopsis(text: str, proname: str) -> tuple[list[str], list[str]]:
    descriptions: list[str] = []

    for syn in _SYNOPSIS_RE.finditer(text):
        if proname not in _FUNCTION_RE.findall(syn.group(1)):
            continue

        open_para = text.rfind("<para", 0, syn.start())
        close_para = text.find("</para>", syn.end())
        inside = (open_para != -1 and close_para != -1
                  and text.find("</para>", open_para, syn.start()) == -1)

        if inside:
            block = text[open_para:close_para] + "</para>"
        else:
            stops = [x for x in (text.find("<synopsis", syn.end()),
                                 text.find("</sect", syn.end())) if x != -1]
            block = text[syn.end():min(stops) if stops else len(text)]

        for _, para in _PARA_RE.findall(_BLOCK_RE.sub(" ", block)):
            if plain := _tidy(_plain(para)):
                descriptions.append(plain)

    return descriptions, []

def lookup(proname: str, sgml_dir: Path | None = None) -> dict:
    sgml_dir = sgml_dir or (settings.PG_SRC / "doc/src/sgml")
    descriptions, examples = [], []

    for _, text in _sgml(str(sgml_dir)):
        if proname not in text:
            continue
        for source in (_from_table, _from_section, _from_synopsis):
            found_desc, found_examples = source(text, proname)
            descriptions.extend(found_desc)
            examples.extend(found_examples)

    seen: set[str] = set()
    paragraphs = [d for d in descriptions if not (d in seen or seen.add(d))]
    seen = set()
    examples = [e for e in examples if not (e in seen or seen.add(e))]

    kept: list[str] = []
    budget = MAX_DESCRIPTION
    for para in paragraphs:
        if len(para) + 1 > budget:
            break
        kept.append(para)
        budget -= len(para) + 1

    return {"description": "\n".join(kept), "examples": examples}
