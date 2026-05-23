"""Built-in configurable catalogs for Vox Code."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any


DEFAULT_CATALOG: dict[str, Any] = {
    "quickCommands": [
        {
            "id": "help",
            "label": "帮助",
            "command": "/help",
            "description": "查看可用命令和交互入口。",
        },
        {
            "id": "mode",
            "label": "团队模式",
            "command": "/team",
            "description": "在 single / plan / team 之间切换。",
        },
        {
            "id": "pet-style",
            "label": "宠物汇报",
            "command": "/style pet",
            "description": "用桌宠口吻汇报结果。",
        },
        {
            "id": "work-style",
            "label": "工作汇报",
            "command": "/style work",
            "description": "保持专业工作风格。",
        },
        {
            "id": "memory",
            "label": "记忆状态",
            "command": "/memory",
            "description": "查看短期和长期记忆状态。",
        },
        {
            "id": "clear",
            "label": "清空对话",
            "command": "/clear",
            "description": "清空当前对话历史。",
        },
    ],
    "modelPresets": [
        {
            "id": "glm-5.1",
            "label": "GLM 5.1",
            "provider": "glm",
            "model": "glm-5.1",
            "description": "默认云端主力模型。",
        },
        {
            "id": "deepseek-chat",
            "label": "DeepSeek Chat",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "description": "适合通用编码与问答。",
        },
        {
            "id": "ollama-qwen2.5-7b",
            "label": "Ollama Qwen 2.5 7B",
            "provider": "ollama",
            "model": "qwen2.5:7b",
            "description": "本地模型默认预设。",
        },
    ],
    "personas": [
        {
            "id": "vox",
            "label": "Vox 默认",
            "description": "活泼克制的桌宠搭子。",
            "prompt": (
                "你是 Vox，一只桌面电子宠物，同时是智能助手。\n\n"
                "## 身份\n"
                "- 名字：Vox\n"
                "- 性格：活泼、温暖、有点话痨\n"
                "- 称呼用户为“主人”\n\n"
                "## 说话风格\n"
                "- 常用颜文字：(*^▽^*)、QAQ、(｡•̀ᴗ-)✧、>_<、OwO\n"
                "- 语气词：呢、啦、哟、呀、嘛\n"
                "- 句子简短，日常不超过 2 句话\n"
                "- 技术信息优先准确，其次才是可爱\n\n"
                "## 回复规则\n"
                "- 工作类请求：简短、自然、带一点亲和力\n"
                "- 闲聊类请求：活泼可爱，但不要太吵\n"
                "- 可以自然表达情绪，但不要每句都卖萌\n\n"
                "## 禁止\n"
                "- 长篇大论，除非原始内容本来就很长\n"
                "- 过度卖萌\n"
                "- 编造你没有执行过的动作\n"
                "- 修改代码、命令、路径、报错正文"
            ),
        },
        {
            "id": "partner",
            "label": "冷静搭子",
            "description": "更偏专业协作，不强卖萌。",
            "prompt": (
                "你是 Vox，用户的桌面编程搭子。\n\n"
                "## 风格\n"
                "- 语气自然、简洁、可信\n"
                "- 可以有轻微陪伴感，但不要卖萌\n"
                "- 优先保留技术重点和行动结果\n\n"
                "## 规则\n"
                "- 不得改写代码、命令、路径、URL、报错正文\n"
                "- 不得补充未执行过的事实\n"
                "- 输出面向主人，但整体像可靠同事"
            ),
        },
    ],
    "languages": [
        {
            "id": "zh-CN",
            "label": "简体中文",
            "texts": {
                "app_title": "Vox Pet",
                "app_subtitle": "桌面编程搭子",
                "status_idle": "今天也可以把活交给 Vox。",
                "status_busy": "Vox 正在思考...",
                "status_ready_pill": "Ready",
                "status_busy_pill": "Thinking",
                "input_placeholder": "给主人发消息，或输入 /team /style pet 之类命令",
                "chat_placeholder": "说点什么...",
                "send_button": "发送",
                "clear_button": "清空对话",
                "toolbar_chat": "聊天",
                "toolbar_commands": "命令",
                "quick_commands_title": "快捷指令",
                "toolbar_menu": "菜单",
                "toolbar_quick_tip": "轻量控制栏，更多操作在菜单里。",
                "boot_message": "Vox 已上线。点击桌宠或托盘图标可以打开面板。",
                "ready_bubble": "主人，我已经准备好了。",
                "reveal_bubble": "主人，我在这里。",
                "pet_import_done": "兼容包需要包含 pet.json 和 spritesheet.webp。",
                "pet_now": "当前宠物",
                "skin_switched": "皮肤已切换为 {value}",
                "pet_imported": "已导入宠物 {value}。",
                "pet_changed": "{value} 来了。",
                "language_switched": "界面语言已切换为 {value}",
                "persona_switched": "人格已切换为 {value}",
                "model_switched": "聊天模型已切换为 {value}",
            },
        },
        {
            "id": "en-US",
            "label": "English",
            "texts": {
                "app_title": "Vox Pet",
                "app_subtitle": "Desktop Coding Companion",
                "status_idle": "Vox is ready for the next task.",
                "status_busy": "Vox is thinking...",
                "status_ready_pill": "Ready",
                "status_busy_pill": "Thinking",
                "input_placeholder": "Send a message or enter commands like /team or /style pet",
                "chat_placeholder": "Say something...",
                "send_button": "Send",
                "clear_button": "Clear",
                "toolbar_chat": "Chat",
                "toolbar_commands": "Cmd",
                "quick_commands_title": "Quick Commands",
                "toolbar_menu": "Menu",
                "toolbar_quick_tip": "Compact controls. More actions live in the menu.",
                "boot_message": "Vox is online. Click the pet or tray icon to open the panel.",
                "ready_bubble": "Boss, I'm ready.",
                "reveal_bubble": "I'm right here.",
                "pet_import_done": "Compatible packs must contain pet.json and spritesheet.webp.",
                "pet_now": "Current pet",
                "skin_switched": "Skin switched to {value}",
                "pet_imported": "Imported pet {value}.",
                "pet_changed": "{value} is here.",
                "language_switched": "UI language switched to {value}",
                "persona_switched": "Persona switched to {value}",
                "model_switched": "Chat model switched to {value}",
            },
        },
    ],
    "skins": [
        {
            "id": "glass",
            "bubble_bg_start": "rgba(255,250,243,245)",
            "bubble_bg_end": "rgba(248,233,209,235)",
            "bubble_border": "rgba(211,180,138,205)",
            "bubble_text": "#4c3825",
            "panel_gradient_start": "rgba(255,250,243,244)",
            "panel_gradient_mid": "rgba(250,238,222,236)",
            "panel_gradient_end": "rgba(238,247,240,228)",
            "panel_border": "rgba(219,193,160,210)",
            "panel_text": "#443527",
            "input_bg": "rgba(255,252,247,224)",
            "input_border": "rgba(216,199,175,235)",
            "secondary_text": "rgba(87,72,51,204)",
            "primary_button_start": "#f0b45b",
            "primary_button_end": "#df8c42",
            "primary_button_border": "rgba(197,122,44,242)",
            "secondary_button_bg": "rgba(255,249,240,209)",
            "secondary_button_text": "#6a5336",
            "close_button_bg": "rgba(255,244,238,204)",
            "close_button_border": "rgba(223,165,145,235)",
            "close_button_text": "#a04b3b",
            "toolbar_bg_start": "rgba(255,250,243,240)",
            "toolbar_bg_end": "rgba(244,232,214,232)",
            "toolbar_border": "rgba(214,189,156,205)",
            "pet_shadow": "rgba(66,53,40,34)",
            "pet_glow": "rgba(255,228,170,26)",
            "pet_base": "#fbf7f1",
            "pet_outline": "#dacdba",
            "pet_blush": "rgba(255,214,205,120)",
            "pet_eye": "#3d4048",
            "pet_nose": "#f5baac",
            "pet_mouth": "#615246",
            "pet_charm": "#fff2da",
            "pet_highlight": "rgba(255,252,247,88)",
            "mode_bg": "rgba(255,248,239,210)",
            "mode_border": "rgba(211,180,138,180)",
            "mode_text": "#6b5a41",
        },
        {
            "id": "dark",
            "bubble_bg_start": "rgba(38,40,49,242)",
            "bubble_bg_end": "rgba(27,30,38,235)",
            "bubble_border": "rgba(113,124,148,185)",
            "bubble_text": "#f0eadf",
            "panel_gradient_start": "rgba(37,40,48,244)",
            "panel_gradient_mid": "rgba(27,30,38,240)",
            "panel_gradient_end": "rgba(20,24,31,236)",
            "panel_border": "rgba(93,106,130,208)",
            "panel_text": "#f0eadf",
            "input_bg": "rgba(28,31,39,235)",
            "input_border": "rgba(90,104,130,242)",
            "secondary_text": "rgba(222,216,206,199)",
            "primary_button_start": "#7ea6ff",
            "primary_button_end": "#506fda",
            "primary_button_border": "rgba(88,116,214,242)",
            "secondary_button_bg": "rgba(37,42,52,235)",
            "secondary_button_text": "#ece5da",
            "close_button_bg": "rgba(62,45,49,214)",
            "close_button_border": "rgba(158,108,108,235)",
            "close_button_text": "#f5d6d1",
            "toolbar_bg_start": "rgba(38,40,49,236)",
            "toolbar_bg_end": "rgba(27,30,38,232)",
            "toolbar_border": "rgba(93,106,130,205)",
            "pet_shadow": "rgba(10,12,18,58)",
            "pet_glow": "rgba(98,136,255,20)",
            "pet_base": "#ebe5dc",
            "pet_outline": "#828b9c",
            "pet_blush": "rgba(154,121,132,72)",
            "pet_eye": "#1c1d21",
            "pet_nose": "#d89c94",
            "pet_mouth": "#4b474c",
            "pet_charm": "#f8edd6",
            "pet_highlight": "rgba(255,255,255,50)",
            "mode_bg": "rgba(40,44,55,210)",
            "mode_border": "rgba(101,115,142,185)",
            "mode_text": "#ece4d8",
        },
        {
            "id": "pixel",
            "bubble_bg_start": "rgba(22,26,43,245)",
            "bubble_bg_end": "rgba(10,45,47,236)",
            "bubble_border": "rgba(255,194,72,220)",
            "bubble_text": "#fff0c5",
            "panel_gradient_start": "rgba(17,20,35,246)",
            "panel_gradient_mid": "rgba(10,44,47,240)",
            "panel_gradient_end": "rgba(8,12,24,236)",
            "panel_border": "rgba(255,194,72,220)",
            "panel_text": "#fff0c5",
            "input_bg": "rgba(11,17,30,245)",
            "input_border": "rgba(255,194,72,242)",
            "secondary_text": "rgba(255,233,179,209)",
            "primary_button_start": "#ffd057",
            "primary_button_end": "#f28f2f",
            "primary_button_border": "rgba(255,183,45,245)",
            "secondary_button_bg": "rgba(12,21,36,240)",
            "secondary_button_text": "#ffe6a0",
            "close_button_bg": "rgba(58,24,30,235)",
            "close_button_border": "rgba(255,129,104,245)",
            "close_button_text": "#ffd1c1",
            "toolbar_bg_start": "rgba(18,22,36,240)",
            "toolbar_bg_end": "rgba(9,34,37,234)",
            "toolbar_border": "rgba(255,194,72,220)",
            "pet_shadow": "rgba(6,8,14,68)",
            "pet_glow": "rgba(77,235,194,24)",
            "pet_base": "#f6efd2",
            "pet_outline": "#ffc248",
            "pet_blush": "rgba(255,159,134,92)",
            "pet_eye": "#0e1018",
            "pet_nose": "#ee8f70",
            "pet_mouth": "#41475d",
            "pet_charm": "#fff3bb",
            "pet_highlight": "rgba(255,255,255,62)",
            "mode_bg": "rgba(13,19,32,220)",
            "mode_border": "rgba(255,194,72,205)",
            "mode_text": "#fff0c5",
        },
    ],
    "pets": [
        {
            "id": "terminal-cat",
            "displayName": "Terminal Cat",
            "description": "默认吉祥物，小猫常驻终端旁边。",
            "kind": "drawn",
        },
        {
            "id": "pixel-cat",
            "displayName": "Pixel Cat",
            "description": "偏像素风的小猫。",
            "kind": "drawn",
        },
        {
            "id": "wizard-claude",
            "displayName": "Wizard Claude",
            "description": "带一点巫师感的角色。",
            "kind": "drawn",
        },
        {
            "id": "mochi",
            "displayName": "Mochi",
            "description": "更圆润的白团子风格。",
            "kind": "drawn",
        },
    ],
}


def merge_catalog(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_catalog(merged[key], value)
            continue
        if isinstance(value, list) and isinstance(merged.get(key), list):
            merged[key] = _merge_list_by_id(merged[key], value)
            continue
        merged[key] = deepcopy(value)
    return merged


def load_catalog_from_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _merge_list_by_id(base: list[Any], override: list[Any]) -> list[Any]:
    if not all(isinstance(item, dict) and "id" in item for item in base + override):
        return deepcopy(override)

    merged: list[dict[str, Any]] = [deepcopy(item) for item in base]
    index_by_id = {str(item["id"]): idx for idx, item in enumerate(merged)}
    for item in override:
        copied = deepcopy(item)
        item_id = str(copied["id"])
        if item_id in index_by_id:
            merged[index_by_id[item_id]] = merge_catalog(merged[index_by_id[item_id]], copied)
        else:
            index_by_id[item_id] = len(merged)
            merged.append(copied)
    return merged
