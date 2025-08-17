# payout_bot.py
import logging
import os
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен в переменных окружения.")

NOWPAYMENTS_API_KEY = os.getenv('NOWPAYMENTS_API_KEY', 'YOUR_NOWPAYMENTS_API_KEY_HERE')
if NOWPAYMENTS_API_KEY == 'YOUR_NOWPAYMENTS_API_KEY_HERE':
    logger.warning("NOWPAYMENTS_API_KEY использует значение по умолчанию. Убедитесь, что он установлен правильно.")

WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://your-app-url.onrender.com') # Необходим для IPN, если используется webhook

# Доступные криптовалюты для оплаты (обновленный список из оплата.txt)
AVAILABLE_CURRENCIES = {
    "USDT (Solana)": "usdtsol",
    "USDT (TRC20)": "usdttrc20",
    "ETH": "eth",
    "USDT (Arbitrum)": "usdtarb",
    "USDT (Polygon)": "usdtmatic",
    "USDT (TON)": "usdtton",
    "AVAX (C-Chain)": "avax",
    "APTOS (APT)": "apt"
}

# Курс для конвертации UAH в USD
EXCHANGE_RATE_UAH_TO_USD = 41.26

# ID основателей для проверки доступа
OWNER_ID_1 = 7106925462
OWNER_ID_2 = 6279578957
OWNER_IDS = {OWNER_ID_1, OWNER_ID_2}


def convert_uah_to_usd(uah_amount: float) -> float:
    """Конвертирует сумму из UAH в USD по фиксированному курсу."""
    if uah_amount <= 0:
        return 0.0
    return round(uah_amount / EXCHANGE_RATE_UAH_TO_USD, 2)


async def payout_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /payout для основателей"""
    user = update.effective_user
    user_id = user.id

    # Проверяем, является ли пользователь основателем
    if user_id not in OWNER_IDS:
        await update.message.reply_text("❌ У вас немає доступу до цієї команди.")
        return

    # Проверяем аргументы команды
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Неправильний формат команди.\n"
            "Використовуйте: `/payout <user_id> <amount_in_uah>`\n"
            "Наприклад: `/payout 123456789 500`",
            parse_mode='Markdown'
        )
        return

    try:
        target_user_id = int(context.args[0])
        uah_amount = float(context.args[1])
        if uah_amount <= 0:
            raise ValueError("Сума повинна бути більше нуля.")
    except ValueError as e:
        await update.message.reply_text(f"❌ Неправильний формат ID користувача або суми: {e}")
        return

    # Конвертируем сумму в USD
    usd_amount = convert_uah_to_usd(uah_amount)
    if usd_amount <= 0:
        await update.message.reply_text("❌ Сума в USD занадто мала для створення рахунку.")
        return

    # Сохраняем данные в контексте для последующей обработки
    context.user_data['payout_target_user_id'] = target_user_id
    context.user_data['payout_amount_uah'] = uah_amount
    context.user_data['payout_amount_usd'] = usd_amount

    # Предлагаем выбрать метод оплаты
    keyboard = [
        [InlineKeyboardButton("💳 Оплата карткою", callback_data='payout_card')],
        [InlineKeyboardButton("🪙 Криптовалюта", callback_data='payout_crypto')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='payout_cancel')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"💳 Створення рахунку на {uah_amount}₴ ({usd_amount}$) для користувача `{target_user_id}`.\n"
        f"Оберіть метод оплати:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def payout_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback кнопок, связанных с payout"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    # Проверяем, является ли пользователь основателем
    if user_id not in OWNER_IDS:
        await query.answer("❌ У вас немає доступу.", show_alert=True)
        return

    # Проверяем, есть ли данные в контексте
    target_user_id = context.user_data.get('payout_target_user_id')
    uah_amount = context.user_data.get('payout_amount_uah')
    usd_amount = context.user_data.get('payout_amount_usd')

    if not target_user_id or not uah_amount or not usd_amount:
        await query.edit_message_text("❌ Помилка: інформація про платіж втрачена. Спробуйте ще раз.")
        return

    # --- Логика для /payout ---
    # - Отмена -
    if data == 'payout_cancel':
        await query.edit_message_text("❌ Створення рахунку скасовано.")
        # Очищаем контекст
        context.user_data.pop('payout_target_user_id', None)
        context.user_data.pop('payout_amount_uah', None)
        context.user_data.pop('payout_amount_usd', None)
        context.user_data.pop('payout_nowpayments_invoice_id', None)
        return

    # - Оплата карткой -
    elif data == 'payout_card':
        # Создаем временную ссылку или просто сообщаем пользователю
        # В реальном приложении здесь могут быть реквизиты
        keyboard = [
            [InlineKeyboardButton("✅ Оплачено", callback_data='payout_manual_payment_confirmed')],
            [InlineKeyboardButton("⬅️ Назад", callback_data='payout_cancel')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"💳 Оплата {uah_amount}₴ ({usd_amount}$) карткою.\n"
            f"(Тут будуть реквізити для оплати)\n"
            f"Після оплати натисніть кнопку '✅ Оплачено'.",
            reply_markup=reply_markup
        )
        # Можно установить флаг ожидания подтверждения, если нужно

    # - Оплата криптовалютою -
    elif data == 'payout_crypto':
        # Отображаем список доступных криптовалют
        keyboard = []
        for currency_name, currency_code in AVAILABLE_CURRENCIES.items():
            keyboard.append([InlineKeyboardButton(currency_name, callback_data=f'payout_crypto_{currency_code}')])
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='payout_cancel')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"🪙 Оберіть криптовалюту для створення рахунку на {uah_amount}₴ ({usd_amount}$):",
            reply_markup=reply_markup
        )
        # context.user_data['awaiting_payout_crypto_currency_selection'] = True # Можно использовать, если нужно состояние

    # - Выбор конкретной криптовалюты -
    elif data.startswith('payout_crypto_'):
        pay_currency = data.split('_')[2]  # e.g., 'usdttrc20'
        # Находим название валюты
        currency_name = next((name for name, code in AVAILABLE_CURRENCIES.items() if code == pay_currency), pay_currency)
        try:
            # Создаем счет в NOWPayments
            headers = {
                'Authorization': f'Bearer {NOWPAYMENTS_API_KEY}', # Используем Bearer токен
                'Content-Type': 'application/json'
            }
            payload = {
                "price_amount": usd_amount,
                "price_currency": "usd",
                "pay_currency": pay_currency,
                "ipn_callback_url": f"{WEBHOOK_URL}/nowpayments_ipn",  # URL для уведомлений (если используется webhook)
                "order_id": f"payout_{user_id}_{target_user_id}_{int(time.time())}",  # Уникальный ID
                "order_description": f"Виставлення рахунку основателем {user_id} для користувача {target_user_id}"
            }
            logger.info(f"Создание инвойса NOWPayments: {payload}")
            response = requests.post("https://api.nowpayments.io/v1/invoice", json=payload, headers=headers)
            logger.info(f"Ответ NOWPayments: {response.status_code}, {response.text}")
            response.raise_for_status()
            invoice = response.json()
            pay_url = invoice.get("invoice_url", "Помилка отримання посилання")
            invoice_id = invoice.get("invoice_id", "Невідомий ID рахунку")

            # Сохраняем ID инвойса
            context.user_data['payout_nowpayments_invoice_id'] = invoice_id

            keyboard = [
                [InlineKeyboardButton("🔗 Перейти до оплати", url=pay_url)],
                [InlineKeyboardButton("🔄 Перевірити статус", callback_data='payout_check_payment_status')],
                [InlineKeyboardButton("⬅️ Назад", callback_data='payout_cancel')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            # Отправляем ссылку пользователю
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"🪙 Вам виставлено рахунок на {uah_amount}₴ ({usd_amount}$) в {currency_name}:\n"
                         f"{pay_url}\n"
                         f"ID рахунку: `{invoice_id}`\n"
                         f"Будь ласка, здійсніть оплату.",
                    parse_mode='Markdown'
                )
                await query.edit_message_text(
                    f"✅ Рахунок створено та надіслано користувачу `{target_user_id}`.\n"
                    f"Посилання: {pay_url}",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Помилка надсилання рахунку користувачу {target_user_id}: {e}")
                await query.edit_message_text(
                    f"❌ Рахунок створено, але не вдалося надіслати користувачу: {e}\n"
                    f"Посилання: {pay_url}"
                )
        except requests.exceptions.RequestException as e:
            logger.error(f"Помилка мережі NOWPayments для payout: {e}")
            await query.edit_message_text(f"❌ Помилка з'єднання з сервісом оплати: {e}")
        except Exception as e:
            logger.error(f"Помилка створення інвойсу NOWPayments для payout: {e}")
            await query.edit_message_text(f"❌ Помилка створення посилання для оплати: {e}")

    # - Ручне підтвердження оплати -
    elif data == 'payout_manual_payment_confirmed':
        # Здесь можно добавить логику проверки оплаты вручную или запись в БД
        await query.edit_message_text(
            "✅ Оплата карткою підтверджена вручну.\n"
            "Інформуйте користувача про подальші дії."
        )
        # Очищаем контекст после завершения
        context.user_data.pop('payout_target_user_id', None)
        context.user_data.pop('payout_amount_uah', None)
        context.user_data.pop('payout_amount_usd', None)
        context.user_data.pop('payout_nowpayments_invoice_id', None)

    # - Перевірка статуса оплати -
    elif data == 'payout_check_payment_status':
        invoice_id = context.user_data.get('payout_nowpayments_invoice_id')
        if not invoice_id:
            await query.edit_message_text("❌ Не знайдено ID рахунку для перевірки.")
            return
        try:
            headers = {
                'Authorization': f'Bearer {NOWPAYMENTS_API_KEY}', # Используем Bearer токен
                'Content-Type': 'application/json'
            }
            response = requests.get(f"https://api.nowpayments.io/v1/invoice/{invoice_id}", headers=headers)
            response.raise_for_status()
            status_data = response.json()
            payment_status = status_data.get('payment_status', 'unknown')

            if payment_status == 'finished':
                await query.edit_message_text(
                    "✅ Оплата успішно пройшла!\n"
                    "Інформуйте користувача про подальші дії."
                )
                # Очищаем контекст после успешной оплаты
                context.user_data.pop('payout_target_user_id', None)
                context.user_data.pop('payout_amount_uah', None)
                context.user_data.pop('payout_amount_usd', None)
                context.user_data.pop('payout_nowpayments_invoice_id', None)
            elif payment_status in ['waiting', 'confirming', 'confirmed']:
                keyboard = [
                    [InlineKeyboardButton("🔄 Перевірити ще раз", callback_data='payout_check_payment_status')],
                    [InlineKeyboardButton("⬅️ Назад", callback_data='payout_cancel')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"⏳ Статус оплати: `{payment_status}`. Будь ласка, зачекайте або перевірте ще раз.",
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
            else:  # cancelled, expired, partially_paid, etc.
                keyboard = [
                    [InlineKeyboardButton("💳 Інший метод оплати", callback_data='payout_cancel')], # Просто отмена, можно добавить повторный выбор
                    [InlineKeyboardButton("⬅️ Назад", callback_data='payout_cancel')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"❌ Оплата не пройшла або була скасована. Статус: `{payment_status}`.",
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
        except Exception as e:
            logger.error(f"Помилка перевірки статусу NOWPayments для payout: {e}")
            await query.edit_message_text(f"❌ Помилка перевірки статусу оплати: {e}")


def main():
    """Основная функция для запуска бота payout"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен. Выход.")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    # Добавляем обработчики команд и callback'ов только для payout
    application.add_handler(CommandHandler("payout", payout_command))
    application.add_handler(CallbackQueryHandler(payout_callback_handler, pattern='^payout_'))

    logger.info("Запуск бота для /payout...")
    application.run_polling()


if __name__ == '__main__':
    main()
