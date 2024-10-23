import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    PicklePersistence,
    ConversationHandler,
    CallbackQueryHandler
)
import uuid
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

api_endpoint = os.getenv('API_ENDPOINT')
topic = 3

# conversation states for posting data
TYPING_POST = 0
CONFIRMING_POST = 1

COMMANDS_MESSAGE = (
    "I'm a bot that stores your secret posts in Nillion, then posts them anonymously in the Tea App. Here's what you can ask me to do:\n\n"
    "/post - Anonymously create a new secret post and store it in Nillion\n"
    "/info - Tell you your Nillion User ID, associated with your secret posts\n"
    "/app - Check out the Tea App to see all anonymous posts"
)

def initialize_user_data(context, user):
    """Initialize user data with conversation_id and nillion_seed."""
    username = user.username if user.username else f"{user.first_name} {user.last_name}".strip()
    conversation_id = str(uuid.uuid4())
    context.user_data['conversation_id'] = conversation_id
    context.user_data['nillion_seed'] = f"{username}_{conversation_id}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command"""
    if update.effective_chat.type != 'private':
        await update.message.reply_text("I only work in private chats. Please message me directly.")
        return
    
    user = update.effective_user
    username = user.username if user.username else f"{user.first_name} {user.last_name}".strip()
    
    # Check if conversation_id and nillion_seed exist in user data
    if 'conversation_id' not in context.user_data or 'nillion_seed' not in context.user_data:
        initialize_user_data(context, update.effective_user)
        welcome_message = f"Hi @{username}! Let's get started!\n\nUse /post to create a new post!"
    else:
        welcome_message = f"Welcome back @{username}!"
    
    await update.message.reply_text(welcome_message + "\n\n" + COMMANDS_MESSAGE)

async def start_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the post conversation"""
    if update.effective_chat.type != 'private':
        await update.message.reply_text("I only work in private chats. Please message me directly.")
        return ConversationHandler.END
    
    if 'nillion_seed' not in context.user_data:
        initialize_user_data(context, update.effective_user)
    
    await update.message.reply_text("What do you want to post?")
    return TYPING_POST

async def receive_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive the post content and ask for confirmation"""
    user = update.effective_user
    username = user.username if user.username else f"{user.first_name} {user.last_name}".strip()
    
    # Store the post text and metadata in context
    context.user_data['pending_post'] = {
        "conversation_id": context.user_data['nillion_seed'],
        "telegram_handle": username,
        "message": update.message.text
    }
    
    # inline yes/no buttons
    keyboard = [
        [
            InlineKeyboardButton("Yes", callback_data='confirm_post'),
            InlineKeyboardButton("No", callback_data='cancel_post')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Ask for confirmation
    await update.message.reply_text(
        f"Your post will be stored as a secret message in Nillion. Anyone will be able to read it on the anonymous tea board. Are you sure you want to post this? \n\n{update.message.text}",
        reply_markup=reply_markup
    )
    return CONFIRMING_POST

async def handle_post_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the user's confirmation choice"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'confirm_post':
        try_again_message = "Try again with /post!"
        try:
            api_data = {
                "nillion_seed": context.user_data['nillion_seed'],
                "nillion_secret": context.user_data['pending_post']['message'],
                "secret_name": "confession",
                "topics": [topic]
            }
            
            processing_message = await query.edit_message_text("🛜 Storing your post...")
            
            async with aiohttp.ClientSession() as session:
                api_response = await store_secret_with_api(session, api_endpoint, api_data)
                if api_response:
                    await handle_successful_response(processing_message, api_response, topic)
                else:
                    # Retry 1x
                    logger.info("Retrying the API request...")
                    api_response = await store_secret_with_api(session, api_endpoint, api_data)
                    if api_response:
                        await handle_successful_response(processing_message, api_response, topic)
                    else:
                        await processing_message.edit_text(f"There was an error posting your message. {try_again_message}")
        except Exception as e:
            logger.error(f"An exception occurred: {e}")
            await processing_message.edit_text(f"There was an error posting your message. {try_again_message}")
    else:
        await query.edit_message_text("Post cancelled.")
    
    # Clear the pending post from context
    if 'pending_post' in context.user_data:
        del context.user_data['pending_post']
    
    return ConversationHandler.END

async def cancel_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the post conversation"""
    await update.message.reply_text("Post cancelled.")
    
    # Clear the pending post from context
    if 'pending_post' in context.user_data:
        del context.user_data['pending_post']
    
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")

async def handle_random_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for normal messages"""
    if update.effective_chat.type != 'private':
        return
    
    await update.message.reply_text(COMMANDS_MESSAGE)
    
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /info command"""
    if 'nillion_user_id' in context.user_data:
        nillion_user_id = context.user_data['nillion_user_id']
        await update.message.reply_text(f"Your Nillion User ID is: {nillion_user_id}. This ID is used to identify your posts in Nillion.")
        return  
    else:
        initialize_user_data(context, update.effective_user)

    if 'nillion_seed' in context.user_data:
        nillion_seed = context.user_data['nillion_seed']
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{api_endpoint}/api/user", json={"nillion_seed": nillion_seed}) as response:
                if response.status == 200:
                    api_response = await response.json()
                    nillion_user_id = api_response.get('nillion_user_id')
                    context.user_data['nillion_user_id'] = nillion_user_id 
                    await update.message.reply_text(f"Your new Nillion User ID is: {nillion_user_id}. This ID is used to identify your posts in Nillion.")
                else:
                    logger.error(f"API error: Status {response.status}")
                    await update.message.reply_text("Sorry, there was an error retrieving your user ID.")

    else:
        await update.message.reply_text("You have not started a conversation yet. Please use /start to begin.")

async def open_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /app command"""
    await update.message.reply_text(f"Check out the Tea App: https://tea-frontend-dusky.vercel.app/topic/{topic}")  # Replace with your desired link

async def clear_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for the /clear command"""
    # Clear conversation_id and nillion_seed from user data
    if 'conversation_id' in context.user_data:
        del context.user_data['conversation_id']
    if 'nillion_seed' in context.user_data:
        del context.user_data['nillion_seed']
    if 'nillion_user_id' in context.user_data:
        del context.user_data['nillion_user_id']

    await update.message.reply_text(f"Your conversation data has been cleared.")

async def log_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /log command"""
    await update.message.reply_text(f"User data: {context.user_data}")

async def store_secret_with_api(session, api_endpoint, api_data):
    """Function to make the API request."""
    async with session.post(f"{api_endpoint}/api/secret", json=api_data) as response:
        if response.status == 200:
            api_response = await response.json()
            return api_response
        else:
            logger.error(f"API error: {response}")
            return None

async def handle_successful_response(processing_message, api_response, topic):
    """Handle the successful API response."""
    store_id = api_response.get('store_id')
    await processing_message.edit_text(
        f"Your post has been secretly stored in Nillion.\n"
        f"Nillion Store ID for the post: {store_id}\n"
        f"Check it out on https://tea-frontend-dusky.vercel.app/topic/{topic}"
    )

def main():
    """Start the bot"""
    # Initialize persistence
    persistence = PicklePersistence(filepath="bot_data.pickle")
    
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        logger.error("No bot token found! Make sure TELEGRAM_BOT_TOKEN is set in .env file")
        return

    # Initialize app
    application = Application.builder()\
        .token(bot_token)\
        .persistence(persistence)\
        .build()

    # more complex handlerfor /post command
    post_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('post', start_post)],
        states={
            TYPING_POST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_post)
            ],
            CONFIRMING_POST: [
                CallbackQueryHandler(handle_post_confirmation, pattern='^(confirm|cancel)_post$')
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel_post)],
        name='post_conversation',
        persistent=True
    )

    logger.info("Starting bot...")

    # Run the start handler on new chats with the bot
    application.add_handler(MessageHandler(filters.StatusUpdate.CHAT_CREATED, start))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("info", info))
    application.add_handler(CommandHandler("app", open_app))
    application.add_handler(CommandHandler("clear", clear_data))
    application.add_handler(CommandHandler("log", log_data))
    application.add_handler(post_conv_handler)
    application.add_handler(CommandHandler("post", start_post))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_random_message))
    application.add_error_handler(error_handler)
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
