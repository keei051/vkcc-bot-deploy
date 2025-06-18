from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ReplyKeyboardRemove
from aiogram.dispatcher import FSMContext
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
import aiohttp
import json
import os
import datetime
import logging

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = '7952321153:AAF9oYx8Ov1NgiNe60Y45XZvd-LCiLKMeiM'
VK_TOKEN = 'c26551e5c26551e5c26551e564c1513cc2cc265c26551e5aa37c66a6a6d8f7092ca2102'

LINKS_FILE = 'links.json'

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

class LinkForm(StatesGroup):
    waiting_for_link  = State()
    waiting_for_title = State()
    renaming_link     = State()

main_menu = InlineKeyboardMarkup(row_width=2)
main_menu.add(
    InlineKeyboardButton('➕ Добавить ссылку', callback_data='add_link'),
    InlineKeyboardButton('🔗 Мои ссылки', callback_data='my_links'),
    InlineKeyboardButton('📋 Все ссылки за 7 дней', callback_data='show_all_links')
)

cancel_kb = InlineKeyboardMarkup().add(
    InlineKeyboardButton('❌ Отмена', callback_data='main_menu'),
)

def link_menu(key: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=3)
    kb.add(
        InlineKeyboardButton('📈 Статистика', callback_data=f'stat_{key}'),
        InlineKeyboardButton('✏️ Переименовать', callback_data=f'rename_{key}'),
        InlineKeyboardButton('🗑️ Удалить', callback_data=f'del_{key}'),
    )
    kb.add(
        InlineKeyboardButton('⬅️ Назад', callback_data='my_links'),
        InlineKeyboardButton('🏠 Главное меню', callback_data='main_menu'),
    )
    return kb

def load_links() -> dict:
    if not os.path.exists(LINKS_FILE):
        return {}
    with open(LINKS_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            logging.error("Ошибка чтения links.json — файл повреждён или пустой")
            return {}

def save_links(data: dict) -> None:
    with open(LINKS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def filter_links_by_date(links: list, days: int = 7) -> list:
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    filtered = []
    for l in links:
        try:
            created_date = datetime.datetime.fromisoformat(l['created'])
            if created_date >= cutoff:
                filtered.append(l)
        except Exception as e:
            logging.error(f"Ошибка при фильтрации даты ссылки: {e}")
    return filtered

@dp.message_handler(commands=['start', 'help'])
async def on_start(message: types.Message):
    await message.answer(
        '👋 Привет! Пришли мне HTTPS-ссылку, я её сокращу через vk.cc.\n'
        'Или выбери действие из меню ниже:',
        reply_markup=main_menu
    )
    await message.reply("Добро пожаловать!", reply_markup=ReplyKeyboardRemove())

@dp.callback_query_handler(lambda c: c.data == 'main_menu', state='*')
async def on_main_menu(call: CallbackQuery, state: FSMContext):
    await state.finish()
    await call.message.edit_text('🏠 Главное меню. Выбери действие:', reply_markup=main_menu)
    await call.answer("Вернулись в главное меню")

@dp.callback_query_handler(lambda c: c.data == 'add_link')
async def on_add_link(call: CallbackQuery):
    await call.message.edit_text(
        '🔗 Вставь одну или несколько HTTPS-ссылок (макс. 15), по одной в строке:',
        reply_markup=cancel_kb
    )
    await LinkForm.waiting_for_link.set()
    await call.answer("Жду ссылку")

@dp.message_handler(state=LinkForm.waiting_for_link)
async def on_process_links(message: types.Message, state: FSMContext):
    uid = str(message.from_user.id)
    store = load_links()
    user_links = store.get(uid, [])
    old_urls = {l['original'] for l in user_links}

    urls = [u.strip() for u in message.text.splitlines() if u.strip()]
    if not urls or len(urls) > 15:
        await message.reply('⚠️ Нужно от 1 до 15 ссылок.', reply_markup=cancel_kb)
        return

    shortened, failed, duplicated = [], [], []

    async with aiohttp.ClientSession() as session:
        for url in urls:
            if url in old_urls:
                duplicated.append(url)
                continue
            if not url.startswith('https://'):
                failed.append(url)
                continue
            params = {'access_token': VK_TOKEN, 'v': '5.199', 'url': url}
            try:
                async with session.get('https://api.vk.com/method/utils.getShortLink', params=params) as resp:
                    data = await resp.json()
                    logging.info(f"VK API ответ на utils.getShortLink: {data}")
                    if 'error' in data:
                        failed.append(url)
                        logging.error(f"Ошибка VK API при сокращении ссылки {url}: {data['error']}")
                        continue
                    resp_data = data.get('response')
                    if resp_data:
                        shortened.append((resp_data['key'], resp_data['short_url'], url))
                    else:
                        failed.append(url)
            except Exception as e:
                logging.error(f"Ошибка при запросе VK API: {e}")
                failed.append(url)

    if not shortened:
        await message.reply('⚠️ Ничего не сократилось.', reply_markup=main_menu)
        await state.finish()
        return

    now = datetime.datetime.now().isoformat()
    for key, short_url, original in shortened:
        store.setdefault(uid, []).append({
            'key':     key,
            'short':   short_url,
            'original':original,
            'created': now,
            'title':   ''
        })
    save_links(store)

    reply = f'✅ Сократил {len(shortened)} ссылок.\n'
    reply += f'Последняя: {shortened[-1][1]}\n'
    if duplicated:
        reply += f'⚠️ Пропущены дубли: {len(duplicated)}\n'
    if failed:
        reply += f'⛔ Ошибки: {len(failed)}\n'

    await message.answer(reply + 'Придумай название для последней ссылки:', reply_markup=cancel_kb)
    await state.update_data(last_key=shortened[-1][0])
    await LinkForm.waiting_for_title.set()

@dp.message_handler(state=LinkForm.waiting_for_title)
async def on_set_title(message: types.Message, state: FSMContext):
    uid = str(message.from_user.id)
    title = message.text.strip()
    key = (await state.get_data()).get('last_key')
    data = load_links()
    for link in data.get(uid, []):
        if link['key'] == key:
            link['title'] = title
            break
    save_links(data)
    await state.finish()

    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton('➕ Добавить ещё ссылку', callback_data='add_link'),
        InlineKeyboardButton('🗑️ Удалить последнюю', callback_data=f'del_{key}'),
        InlineKeyboardButton('🏠 Главное меню', callback_data='main_menu'),
    )
    await message.answer('✅ Название сохранено. Что дальше?', reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'my_links')
async def on_show_links(call: CallbackQuery):
    uid = str(call.from_user.id)
    recent = filter_links_by_date(load_links().get(uid, []), 7)
    if not recent:
        await call.message.edit_text('⚠️ Нет ссылок за последние 7 дней.', reply_markup=main_menu)
        return

    kb = InlineKeyboardMarkup(row_width=1)
    for l in recent:
        text = l.get('title') or l['short']
        kb.add(InlineKeyboardButton(text=text[:40], callback_data=f'link_{l["key"]}'))
    kb.add(InlineKeyboardButton('🏠 Главное меню', callback_data='main_menu'))
    await call.message.edit_text('🔗 Твои ссылки за 7 дней:', reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'show_all_links')
async def on_all_links(call: CallbackQuery):
    uid = str(call.from_user.id)
    all_links = load_links().get(uid, [])
    if not all_links:
        await call.message.edit_text('❗️У вас пока нет сохранённых ссылок.', reply_markup=main_menu)
        return
    kb = InlineKeyboardMarkup(row_width=1)
    for l in all_links:
        text = l.get('title') or l['short']
        kb.add(InlineKeyboardButton(text=text[:40], callback_data=f'link_{l["key"]}'))
    kb.add(InlineKeyboardButton('🏠 Главное меню', callback_data='main_menu'))
    await call.message.edit_text('📋 Все ваши ссылки:', reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('link_'))
async def on_link_options(call: CallbackQuery):
    key = call.data.split('_', 1)[1]
    uid = str(call.from_user.id)
    link = next((x for x in load_links().get(uid, []) if x['key'] == key), None)
    if not link:
        await call.answer('Ссылка не найдена.', show_alert=True)
        return
    detail = (
        f"📝 {link.get('title','') or 'Без названия'}\n"
        f"🔗 {link['short']}\n"
        f"⏳ {link['created'][:19]}\n"
        f"{link['original']}"
    )
    await call.message.edit_text(detail, reply_markup=link_menu(key))

@dp.callback_query_handler(lambda c: c.data.startswith('stat_'))
async def on_stat(call: CallbackQuery):
    key = call.data.split('_', 1)[1]
    async with aiohttp.ClientSession() as session:
        params = {'access_token': VK_TOKEN, 'v': '5.199', 'key': key}
        async with session.get('https://api.vk.com/method/utils.getLinkStats', params=params) as resp:
            data = await resp.json()
            logging.info(f"VK API stats response: {data}")
            stats = data.get('response', {}).get('stats', [])
            total = sum(item.get('views', 0) for item in stats)
            await call.message.answer(f'📊 Переходов: {total}')
    await call.answer("Показана статистика")

@dp.callback_query_handler(lambda c: c.data.startswith('del_'))
async def on_delete(call: CallbackQuery):
    key = call.data.split('_', 1)[1]
    uid = str(call.from_user.id)
    data = load_links()
    data[uid] = [l for l in data.get(uid, []) if l['key'] != key]
    save_links(data)
    await call.message.edit_text('🗑️ Ссылка удалена.', reply_markup=main_menu)

@dp.callback_query_handler(lambda c: c.data.startswith('rename_'))
async def on_rename(call: CallbackQuery, state: FSMContext):
    key = call.data.split('_', 1)[1]
    await state.update_data(rename_key=key)
    await call.message.edit_text('✏️ Введите новую подпись для ссылки:', reply_markup=cancel_kb)
    await LinkForm.renaming_link.set()

@dp.message_handler(state=LinkForm.renaming_link)
async def on_renaming(message: types.Message, state: FSMContext):
    uid = str(message.from_user.id)
    new_title = message.text.strip()
    key = (await state.get_data()).get('rename_key')
    data = load_links()
    for l in data.get(uid, []):
        if l['key'] == key:
            l['title'] = new_title
            break
    save_links(data)
    await state.finish()
    await message.answer('✅ Подпись обновлена.', reply_markup=main_menu)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
