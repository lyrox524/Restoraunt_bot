"""aiogram quraşdırılmayıbsa yüngül stub (testlər şəbəkə və Telegram tələb etmir)."""
import os
import sys
import types as _t

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("AIRTABLE_TOKEN", "pat_test")
os.environ.setdefault("AIRTABLE_BASE_ID", "appTEST")

try:
    import aiogram  # noqa: F401
except ImportError:
    def mod(name, **attrs):
        m = _t.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m

    class _F:
        def __getattr__(self, n): return self
        def __eq__(self, o): return self
        __hash__ = object.__hash__
        def __call__(self, *a, **k): return self
        def startswith(self, *a, **k): return self

    class _Deco:
        def __call__(self, *a, **k):
            return lambda fn: fn

    class Dispatcher:
        def __init__(self): self.message = self.callback_query = self.error = _Deco()
        async def start_polling(self, *a, **k): pass

    class Bot:
        def __init__(self, token=None): pass

    class TelegramBadRequest(Exception): pass

    class State:
        pass

    class StatesGroup:
        pass

    class Btn:
        def __init__(self, text, callback_data=None): self.text, self.callback_data = text, callback_data

    class Markup:
        def __init__(self, inline_keyboard): self.inline_keyboard = inline_keyboard

    types = mod("aiogram.types", InlineKeyboardButton=Btn, InlineKeyboardMarkup=Markup, Message=object,
                CallbackQuery=object, User=object, ErrorEvent=object)
    pkg = mod("aiogram", Bot=Bot, Dispatcher=Dispatcher, F=_F(), types=types)
    mod("aiogram.exceptions", TelegramBadRequest=TelegramBadRequest)
    mod("aiogram.filters", CommandObject=object, CommandStart=lambda *a, **k: None)
    mod("aiogram.fsm", )
    mod("aiogram.fsm.context", FSMContext=object)
    mod("aiogram.fsm.state", State=State, StatesGroup=StatesGroup)
    # State() atributları sinif səviyyəsində qalsın
