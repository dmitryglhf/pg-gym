from __future__ import annotations

from typing import cast

CHAT_TEMPLATE = (
    "{{ bos_token }}"
    "{% for message in messages %}"
    "{% if message['role'] == 'user' %}{{ '<｜User｜>' + message['content'] }}"
    "{% elif message['role'] == 'assistant' %}"
    "{{ '<｜Assistant｜>' + message['content'] + eos_token }}"
    "{% else %}{{ raise_exception('Only user and assistant messages are supported') }}"
    "{% endif %}{% endfor %}"
    "{% if add_generation_prompt %}{{ '<｜Assistant｜>' }}{% endif %}"
)


def configure_template(tokenizer, model: str):
    if "deepseek-r1-distill" in model.lower():
        tokenizer.chat_template = CHAT_TEMPLATE
    elif not tokenizer.chat_template:
        raise ValueError(f"{model} has no chat template")
    return tokenizer


def tokenizer_for(model: str):
    from transformers import AutoTokenizer, PreTrainedTokenizerBase

    tokenizer = cast(PreTrainedTokenizerBase, AutoTokenizer.from_pretrained(model))
    return configure_template(tokenizer, model)


def validate_lengths(tokenizer, rows, max_length: int) -> None:
    for index, row in enumerate(rows):
        messages = row.get("messages") or row["prompt"] + row["completion"]
        tokens = tokenizer.apply_chat_template(messages, return_dict=False)
        if len(tokens) > max_length:
            raise ValueError(f"Example {index} has {len(tokens)} tokens, exceeding {max_length}; "
                             "increase max length instead of truncating the target patch")
