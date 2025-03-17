#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
telegram_bot.py - Bot Telegram per l'assistente personale

Questo modulo gestisce tutte le interazioni con Telegram, offrendo un'interfaccia
utente per l'assistente personale. Gestisce comandi, messaggi, callback,
e integra l'API di Anthropic Claude per le risposte intelligenti.
"""

import os
import re
import json
import logging
import asyncio
import datetime
import tempfile
from io import BytesIO
from typing import Dict, List, Optional, Union, Any, Tuple, Callable, Set, BinaryIO
from contextlib import asynccontextmanager
from uuid import uuid4
from pathlib import Path
from functools import wraps

from telegram import (
    Update, Bot, Message, Chat, User, ChatMember, InlineKeyboardButton, 
    InlineKeyboardMarkup, BotCommand, ChatAction, ParseMode, InputMediaPhoto,
    PhotoSize, Voice, Audio, Document, ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove
)
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler, 
    CallbackQueryHandler, ConversationHandler, ContextTypes, CallbackContext,
    filters, AIORateLimiter
)
from telegram.constants import ParseMode

from anthropic_helper import AnthropicHelper, ClaudeException
from data_manager import DataManager

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Stati per la conversazione
(
    MAIN_MENU, 
    FOOD_INVENTORY, 
    MEAL_PLAN, 
    SHOPPING_LIST, 
    HEALTH_TRACKER,
    ADD_FOOD_ITEM,
    DELETE_FOOD_ITEM,
    CREATE_MEAL_PLAN,
    ADD_MEAL,
    CREATE_SHOPPING_LIST,
    ADD_SHOPPING_ITEM,
    MARK_ITEM_COMPLETE,
    ADD_HEALTH_CONDITION,
    ADD_DIETARY_RESTRICTION,
    ADD_SUPPLEMENT,
    ADD_HEALTH_REPORT,
    WAITING_FOR_FOOD_NAME,
    WAITING_FOR_FOOD_CATEGORY,
    WAITING_FOR_FOOD_QUANTITY,
    WAITING_FOR_FOOD_UNIT,
    WAITING_FOR_FOOD_EXPIRY,
    WAITING_FOR_MEAL_PLAN_NAME,
    WAITING_FOR_MEAL_PLAN_START,
    WAITING_FOR_MEAL_PLAN_END,
    WAITING_FOR_MEAL_DATE,
    WAITING_FOR_MEAL_TYPE,
    WAITING_FOR_MEAL_DESCRIPTION,
    WAITING_FOR_SHOPPING_LIST_NAME,
    WAITING_FOR_SHOPPING_ITEM_NAME,
    WAITING_FOR_SHOPPING_ITEM_QUANTITY,
    WAITING_FOR_SHOPPING_ITEM_UNIT,
    WAITING_FOR_SHOPPING_ITEM_CATEGORY,
    WAITING_FOR_HEALTH_CONDITION_NAME,
    WAITING_FOR_HEALTH_CONDITION_DESCRIPTION,
    WAITING_FOR_HEALTH_CONDITION_SEVERITY,
    WAITING_FOR_DIETARY_RESTRICTION_NAME,
    WAITING_FOR_DIETARY_RESTRICTION_FOOD_TYPE,
    WAITING_FOR_DIETARY_RESTRICTION_REASON,
    WAITING_FOR_DIETARY_RESTRICTION_SEVERITY,
    WAITING_FOR_SUPPLEMENT_NAME,
    WAITING_FOR_SUPPLEMENT_DOSAGE,
    WAITING_FOR_SUPPLEMENT_FREQUENCY,
    WAITING_FOR_SUPPLEMENT_PURPOSE,
    WAITING_FOR_HEALTH_REPORT_TYPE,
    WAITING_FOR_HEALTH_REPORT_DATE,
    WAITING_FOR_HEALTH_REPORT_SUMMARY,
    WAITING_FOR_HEALTH_REPORT_DETAILS,
    SETTINGS,
    HELP
) = range(47)

# Callback data prefixes
FOOD_PREFIX = "food:"
MEAL_PREFIX = "meal:"
SHOP_PREFIX = "shop:"
HEALTH_PREFIX = "health:"
SETTING_PREFIX = "setting:"
LIST_PREFIX = "list:"
COMPLETE_PREFIX = "complete:"
DELETE_PREFIX = "delete:"
PAGE_PREFIX = "page:"
CONFIRM_PREFIX = "confirm:"
CANCEL_PREFIX = "cancel:"

# Formati data e ora
DATE_FORMAT = "%Y-%m-%d"
DISPLAY_DATE_FORMAT = "%d/%m/%Y"
TIME_FORMAT = "%H:%M"

# Limiti di caratteri per messaggi Telegram
MAX_MESSAGE_LENGTH = 4096


class UserData:
    """Classe per gestire i dati temporanei dell'utente durante le conversazioni."""
    
    def __init__(self):
        """Inizializza i dati dell'utente."""
        # Dati per l'aggiunta di alimenti
        self.temp_food_item = {}
        
        # Dati per la creazione di piani alimentari
        self.temp_meal_plan = {}
        self.temp_meal = {}
        
        # Dati per la creazione di liste della spesa
        self.temp_shopping_list = {}
        self.temp_shopping_item = {}
        
        # Dati per il monitoraggio sanitario
        self.temp_health_condition = {}
        self.temp_dietary_restriction = {}
        self.temp_supplement = {}
        self.temp_health_report = {}
        
        # Dati di paginazione
        self.current_page = {}
        self.items_per_page = 5
        
        # Cronologia delle conversazioni per Claude
        self.conversation_history = []
        self.last_interaction_time = datetime.datetime.now()
        
        # Contesto corrente
        self.current_context = None
        self.context_id = None


class ChatGPTTelegramBot:
    """
    Classe principale per il bot Telegram che integra Anthropic Claude.
    Gestisce comandi, messaggi e callback per fornire un'interfaccia
    utente all'assistente personale.
    """
    
    def __init__(self, config: Dict[str, Any], openai: AnthropicHelper):
        """
        Inizializza il bot Telegram.
        
        Args:
            config: Configurazione del bot
            openai: Helper di Anthropic per l'integrazione con Claude
        """
        self.config = config
        self.anthropic = openai
        
        # Inizializza il gestore del database
        self.data_manager = DataManager()
        
        # Dizionario per memorizzare i dati degli utenti durante le conversazioni
        self.user_data = {}
        
        # Set di utenti amministratori
        self.admin_user_ids = self._parse_admin_user_ids()
        
        # Set di utenti autorizzati
        self.allowed_user_ids = self._parse_allowed_user_ids()
        
        # Flag per il debugging
        self.debug_mode = os.environ.get('DEBUG_MODE', 'false').lower() == 'true'
        
        # Impostazioni per le risposte in streaming
        self.stream = config.get('stream', True)
        
        # Budget e tracciamento costi
        self.budget_period = config.get('budget_period', 'monthly')
        self.user_budgets = self._parse_user_budgets()
        self.guest_budget = float(config.get('guest_budget', 100.0))
        self.user_usage = {}
        
        # Costruisci l'applicazione Telegram
        self.application = self._build_application()
        
        logger.info("Bot Telegram inizializzato")
    
    def _parse_admin_user_ids(self) -> Set[int]:
        """
        Analizza gli ID degli utenti amministratori dalla configurazione.
        
        Returns:
            Set[int]: Set di ID degli utenti amministratori
        """
        admin_str = self.config.get('admin_user_ids', '-')
        if admin_str == '-':
            return set()
        
        try:
            return {int(user_id.strip()) for user_id in admin_str.split(',') if user_id.strip()}
        except ValueError:
            logger.error("Formato non valido per admin_user_ids. Deve essere una lista di interi separati da virgole.")
            return set()
    
    def _parse_allowed_user_ids(self) -> Optional[Set[int]]:
        """
        Analizza gli ID degli utenti autorizzati dalla configurazione.
        
        Returns:
            Optional[Set[int]]: Set di ID degli utenti autorizzati o None per consentire tutti
        """
        allowed_str = self.config.get('allowed_user_ids', '*')
        if allowed_str == '*':
            return None  # Tutti gli utenti sono autorizzati
        
        try:
            return {int(user_id.strip()) for user_id in allowed_str.split(',') if user_id.strip()}
        except ValueError:
            logger.error("Formato non valido per allowed_user_ids. Deve essere '*' o una lista di interi separati da virgole.")
            return set()  # Nessun utente autorizzato in caso di errore
    
    def _parse_user_budgets(self) -> Dict[int, float]:
        """
        Analizza i budget degli utenti dalla configurazione.
        
        Returns:
            Dict[int, float]: Dizionario di budget per utente
        """
        budget_str = self.config.get('user_budgets', '*')
        if budget_str == '*':
            return {}  # Budget illimitato per tutti
        
        budgets = {}
        try:
            items = budget_str.split(',')
            for item in items:
                if ':' in item:
                    user_id, budget = item.split(':')
                    budgets[int(user_id.strip())] = float(budget.strip())
            return budgets
        except (ValueError, AttributeError):
            logger.error("Formato non valido per user_budgets. Deve essere '*' o una lista di 'id:budget' separati da virgole.")
            return {}
    
    def _build_application(self) -> Application:
        """
        Costruisce l'applicazione Telegram con tutti gli handler.
        
        Returns:
            Application: Applicazione Telegram configurata
        """
        # Configurazione del rate limiter
        rate_limiter = AIORateLimiter(
            overall_max_rate=30,
            overall_time_period=1,
            group_max_rate=20,
            group_time_period=1,
            max_retries=3,
            retry_delay=0.1
        )
        
        # Costruisci l'applicazione
        application = (
            ApplicationBuilder()
            .token(self.config['token'])
            .rate_limiter(rate_limiter)
            .build()
        )
        
        # Aggiungi gli handler per i comandi principali
        application.add_handler(CommandHandler("start", self.command_start))
        application.add_handler(CommandHandler("help", self.command_help))
        application.add_handler(CommandHandler("reset", self.command_reset))
        application.add_handler(CommandHandler("menu", self.command_menu))
        application.add_handler(CommandHandler("settings", self.command_settings))
        application.add_handler(CommandHandler("cancel", self.command_cancel))
        
        # Handler per i comandi amministrativi
        application.add_handler(CommandHandler("stats", self.command_stats))
        application.add_handler(CommandHandler("broadcast", self.command_broadcast))
        application.add_handler(CommandHandler("debug", self.command_debug))
        
        # Handler per i messaggi di testo generici
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Handler per le immagini (per l'analisi degli alimenti o ricevute)
        application.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
        
        # Handler per i documenti (per l'importazione di dati)
        application.add_handler(MessageHandler(filters.Document.ALL, self.handle_document))
        
        # Handler per i callback da pulsanti inline
        application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # Handler per gli errori
        application.add_error_handler(self.error_handler)
        
        # Definizione della conversazione principale con gli stati
        # (In una versione più complessa, potremmo usare ConversationHandler)
        
        return application
    
    async def set_bot_commands(self, bot: Bot):
        """
        Imposta i comandi disponibili nel menu del bot.
        
        Args:
            bot: Istanza del bot Telegram
        """
        commands = [
            BotCommand("start", "Avvia il bot e mostra il messaggio di benvenuto"),
            BotCommand("menu", "Mostra il menu principale"),
            BotCommand("help", "Mostra aiuto sull'utilizzo del bot"),
            BotCommand("settings", "Gestisci le impostazioni"),
            BotCommand("reset", "Resetta la conversazione corrente"),
            BotCommand("cancel", "Annulla l'operazione corrente")
        ]
        
        await bot.set_my_commands(commands)
        logger.info("Comandi del bot impostati")
    
    def run(self):
        """Avvia il bot Telegram."""
        # Inizializza il database
        self.data_manager.initialize_database()
        
        # Avvia i backup regolari
        asyncio.create_task(self.data_manager.schedule_regular_backups())
        
        # Imposta i comandi del bot all'avvio
        async def post_init(application: Application):
            await self.set_bot_commands(application.bot)
        
        self.application.post_init = post_init
        
        # Avvia il polling
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)
    
    def is_allowed(self, user_id: int) -> bool:
        """
        Controlla se un utente è autorizzato a utilizzare il bot.
        
        Args:
            user_id: ID utente Telegram
            
        Returns:
            bool: True se l'utente è autorizzato, False altrimenti
        """
        # Gli amministratori sono sempre autorizzati
        if user_id in self.admin_user_ids:
            return True
        
        # Se allowed_user_ids è None, tutti sono autorizzati
        if self.allowed_user_ids is None:
            return True
        
        # Altrimenti, controlla se l'utente è nella lista
        return user_id in self.allowed_user_ids
    
    def is_admin(self, user_id: int) -> bool:
        """
        Controlla se un utente è un amministratore del bot.
        
        Args:
            user_id: ID utente Telegram
            
        Returns:
            bool: True se l'utente è un amministratore, False altrimenti
        """
        return user_id in self.admin_user_ids
    
    def get_user_data(self, user_id: int) -> UserData:
        """
        Ottiene i dati temporanei dell'utente, inizializzandoli se necessario.
        
        Args:
            user_id: ID utente Telegram
            
        Returns:
            UserData: Oggetto con i dati dell'utente
        """
        if user_id not in self.user_data:
            self.user_data[user_id] = UserData()
        return self.user_data[user_id]
    
    async def reset_user_data(self, user_id: int):
        """
        Resetta i dati temporanei dell'utente.
        
        Args:
            user_id: ID utente Telegram
        """
        if user_id in self.user_data:
            # Preserva la cronologia delle conversazioni
            history = self.user_data[user_id].conversation_history
            last_time = self.user_data[user_id].last_interaction_time
            
            # Resetta i dati
            self.user_data[user_id] = UserData()
            
            # Ripristina la cronologia
            self.user_data[user_id].conversation_history = history
            self.user_data[user_id].last_interaction_time = last_time
    
    async def command_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce il comando /start.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
        """
        if not update.effective_user:
            return
        
        user_id = update.effective_user.id
        
        # Controlla se l'utente è autorizzato
        if not self.is_allowed(user_id):
            await update.message.reply_text(
                "Mi dispiace, non sei autorizzato a utilizzare questo bot. "
                "Contatta l'amministratore per l'accesso."
            )
            return
        
        # Resetta i dati dell'utente
        await self.reset_user_data(user_id)
        
        # Salva i dati utente nel database se è la prima volta
        # TODO: Implementare la creazione dell'utente nel database
        
        # Messaggio di benvenuto
        welcome_text = (
            f"👋 Benvenuto nell'Assistente Personale Claude!\n\n"
            f"Sono qui per aiutarti a gestire:\n"
            f"🍎 Inventario alimentare\n"
            f"🍽️ Piani alimentari\n"
            f"🛒 Liste della spesa\n"
            f"❤️ Monitoraggio sanitario\n\n"
            f"Usa /menu per accedere alle funzionalità o chiedimi direttamente ciò di cui hai bisogno."
        )
        
        # Crea la tastiera con i pulsanti principali
        keyboard = [
            [KeyboardButton("🍎 Inventario"), KeyboardButton("🍽️ Piani Alimentari")],
            [KeyboardButton("🛒 Lista Spesa"), KeyboardButton("❤️ Salute")],
            [KeyboardButton("❓ Aiuto"), KeyboardButton("⚙️ Impostazioni")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    
    async def command_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce il comando /help.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
        """
        if not update.effective_user:
            return
        
        user_id = update.effective_user.id
        
        # Controlla se l'utente è autorizzato
        if not self.is_allowed(user_id):
            return
        
        help_text = (
            "🤖 *Guida all'Assistente Personale Claude*\n\n"
            "*Comandi principali:*\n"
            "/start - Avvia il bot\n"
            "/menu - Mostra il menu principale\n"
            "/help - Mostra questa guida\n"
            "/settings - Gestisci le tue impostazioni\n"
            "/reset - Resetta la conversazione corrente\n"
            "/cancel - Annulla l'operazione corrente\n\n"
            
            "*Funzionalità disponibili:*\n\n"
            
            "*🍎 Inventario Alimentare*\n"
            "- Aggiungi/rimuovi alimenti\n"
            "- Traccia le scadenze\n"
            "- Visualizza gli alimenti disponibili\n\n"
            
            "*🍽️ Piani Alimentari*\n"
            "- Crea piani settimanali/mensili\n"
            "- Aggiungi pasti ai tuoi piani\n"
            "- Consulta i pasti pianificati\n\n"
            
            "*🛒 Lista della Spesa*\n"
            "- Crea liste personalizzate\n"
            "- Aggiungi articoli alla lista\n"
            "- Genera liste in base all'inventario\n\n"
            
            "*❤️ Monitoraggio Sanitario*\n"
            "- Registra condizioni mediche\n"
            "- Traccia l'assunzione di integratori\n"
            "- Memorizza referti e restrizioni alimentari\n\n"
            
            "*Utilizzo dell'intelligenza artificiale:*\n"
            "Puoi chiedermi qualsiasi cosa riguardo a nutrizione, ricette, consigli alimentari in base alle tue condizioni, "
            "e ti risponderò grazie all'AI di Claude. Puoi anche inviarmi foto di alimenti o ricevute per aiutarti "
            "nell'aggiornamento dell'inventario o delle liste della spesa.\n\n"
            
            "Per qualsiasi dubbio o assistenza, usa il comando /help o chiedi direttamente!"
        )
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    async def command_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce il comando /menu.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
        """
        if not update.effective_user:
            return
        
        user_id = update.effective_user.id
        
        # Controlla se l'utente è autorizzato
        if not self.is_allowed(user_id):
            return
        
        # Resetta lo stato corrente
        await self.reset_user_data(user_id)
        
        # Crea la tastiera inline per il menu principale
        keyboard = [
            [
                InlineKeyboardButton("🍎 Inventario Alimentare", callback_data="menu:inventory"),
                InlineKeyboardButton("🍽️ Piani Alimentari", callback_data="menu:meal_plans")
            ],
            [
                InlineKeyboardButton("🛒 Lista della Spesa", callback_data="menu:shopping"),
                InlineKeyboardButton("❤️ Monitoraggio Sanitario", callback_data="menu:health")
            ],
            [
                InlineKeyboardButton("⚙️ Impostazioni", callback_data="menu:settings"),
                InlineKeyboardButton("❓ Aiuto", callback_data="menu:help")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🔍 *Menu Principale*\n\n"
            "Seleziona una categoria per iniziare:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def command_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce il comando /settings.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
        """
        if not update.effective_user:
            return
        
        user_id = update.effective_user.id
        
        # Controlla se l'utente è autorizzato
        if not self.is_allowed(user_id):
            return
        
        # Ottieni le preferenze utente dal database
        preferences = self.data_manager.get_all_user_preferences(user_id)
        
        # Valori predefiniti se non impostati
        notification_enabled = preferences.get('notifications_enabled', 'true') == 'true'
        expiry_days = int(preferences.get('expiry_notification_days', '3'))
        language = preferences.get('language', 'it')
        
        # Crea la tastiera inline per le impostazioni
        keyboard = [
            [
                InlineKeyboardButton(
                    f"🔔 Notifiche: {'Attive' if notification_enabled else 'Disattive'}", 
                    callback_data=f"setting:notifications:{'false' if notification_enabled else 'true'}"
                )
            ],
            [
                InlineKeyboardButton(
                    f"⏰ Giorni notifica scadenza: {expiry_days}",
                    callback_data="setting:expiry_days"
                )
            ],
            [
                InlineKeyboardButton(
                    f"🌐 Lingua: {language.upper()}",
                    callback_data="setting:language"
                )
            ],
            [
                InlineKeyboardButton(
                    "📤 Esporta dati",
                    callback_data="setting:export_data"
                ),
                InlineKeyboardButton(
                    "📥 Importa dati",
                    callback_data="setting:import_data"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 Torna al menu",
                    callback_data="menu:back"
                )
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "⚙️ *Impostazioni*\n\n"
            "Personalizza il tuo assistente:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def command_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce il comando /reset.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
        """
        if not update.effective_user:
            return
        
        user_id = update.effective_user.id
        
        # Controlla se l'utente è autorizzato
        if not self.is_allowed(user_id):
            return
        
        # Resetta i dati dell'utente inclusa la cronologia delle conversazioni
        if user_id in self.user_data:
            self.user_data[user_id] = UserData()
        
        await update.message.reply_text(
            "🔄 La conversazione è stata resettata. Usa /menu per iniziare una nuova conversazione."
        )
    
    async def command_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce il comando /cancel.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
        """
        if not update.effective_user:
            return
        
        user_id = update.effective_user.id
        
        # Controlla se l'utente è autorizzato
        if not self.is_allowed(user_id):
            return
        
        # Resetta i dati temporanei ma mantieni la cronologia
        await self.reset_user_data(user_id)
        
        await update.message.reply_text(
            "❌ Operazione annullata. Usa /menu per tornare al menu principale."
        )
    
    async def command_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce il comando /stats (solo per amministratori).
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
        """
        if not update.effective_user:
            return
        
        user_id = update.effective_user.id
        
        # Controlla se l'utente è un amministratore
        if not self.is_admin(user_id):
            await update.message.reply_text(
                "⛔ Questo comando è riservato agli amministratori."
            )
            return
        
        # Ottieni statistiche dal database
        db_stats = self.data_manager.get_database_stats()
        
        # Formatta il messaggio con le statistiche
        stats_text = (
            "📊 *Statistiche del Sistema*\n\n"
            f"*Database*\n"
            f"- Dimensione: {db_stats['db_size_mb']} MB\n"
            f"- Ultimo backup: {db_stats.get('last_backup', {}).get('date', 'Mai')}\n\n"
            
            f"*Tabelle*\n"
        )
        
        # Aggiungi statistiche per ogni tabella
        for table, count in db_stats['tables'].items():
            stats_text += f"- {table}: {count} righe\n"
        
        stats_text += "\n*Utenti attivi*\n"
        stats_text += f"- Totale: {len(self.user_data)}\n"
        
        # Aggiungi statistiche sull'utilizzo delle API
        stats_text += "\n*Utilizzo API*\n"
        # TODO: Aggiungi statistiche sulle chiamate API
        
        await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)
    
    async def command_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce il comando /broadcast (solo per amministratori).
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
        """
        if not update.effective_user or not context.args:
            return
        
        user_id = update.effective_user.id
        
        # Controlla se l'utente è un amministratore
        if not self.is_admin(user_id):
            await update.message.reply_text(
                "⛔ Questo comando è riservato agli amministratori."
            )
            return
        
        # Ottieni il messaggio da inviare
        message_text = " ".join(context.args)
        
        # Ottieni tutti gli utenti attivi
        active_users = list(self.user_data.keys())
        
        await update.message.reply_text(
            f"📣 Invio messaggio a {len(active_users)} utenti..."
        )
        
        # Invia il messaggio a tutti gli utenti attivi
        sent_count = 0
        failed_count = 0
        
        for user_id in active_users:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"📣 *Messaggio dall'amministratore*\n\n{message_text}",
                    parse_mode=ParseMode.MARKDOWN
                )
                sent_count += 1
            except Exception as e:
                logger.error(f"Errore nell'invio del messaggio all'utente {user_id}: {str(e)}")
                failed_count += 1
        
        await update.message.reply_text(
            f"📣 Messaggio inviato a {sent_count} utenti.\n"
            f"❌ Fallito l'invio a {failed_count} utenti."
        )
    
    async def command_debug(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce il comando /debug (solo per amministratori).
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
        """
        if not update.effective_user:
            return
        
        user_id = update.effective_user.id
        
        # Controlla se l'utente è un amministratore
        if not self.is_admin(user_id):
            await update.message.reply_text(
                "⛔ Questo comando è riservato agli amministratori."
            )
            return
        
        # Alterna la modalità debug
        self.debug_mode = not self.debug_mode
        
        await update.message.reply_text(
            f"🐞 Modalità debug: {'Attivata' if self.debug_mode else 'Disattivata'}"
        )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce i messaggi di testo generici.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
        """
        if not update.effective_user or not update.message or not update.message.text:
            return
        
        user_id = update.effective_user.id
        message_text = update.message.text
        
        # Controlla se l'utente è autorizzato
        if not self.is_allowed(user_id):
            return
        
        # Ottieni i dati dell'utente
        user_data = self.get_user_data(user_id)
        
        # Gestione dei pulsanti della tastiera principale
        if message_text == "🍎 Inventario":
            await self.show_inventory_menu(update, context)
            return
        elif message_text == "🍽️ Piani Alimentari":
            await self.show_meal_plan_menu(update, context)
            return
        elif message_text == "🛒 Lista Spesa":
            await self.show_shopping_list_menu(update, context)
            return
        elif message_text == "❤️ Salute":
            await self.show_health_menu(update, context)
            return
        elif message_text == "❓ Aiuto":
            await self.command_help(update, context)
            return
        elif message_text == "⚙️ Impostazioni":
            await self.command_settings(update, context)
            return
        
        # Se siamo in attesa di input specifici per completare un'operazione
        if user_data.current_context:
            # Gestisci l'input in base al contesto corrente
            await self.handle_context_input(update, context, user_data.current_context, message_text)
            return
        
        # Altrimenti, invia il messaggio a Claude per un'elaborazione con AI
        await self.process_with_ai(update, context)
    
    async def handle_context_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                  current_context: int, message_text: str):
        """
        Gestisce l'input dell'utente in base al contesto corrente.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            current_context: Stato corrente della conversazione
            message_text: Testo del messaggio
        """
        user_id = update.effective_user.id
        user_data = self.get_user_data(user_id)
        
        # Gestisci ogni stato possibile
        if current_context == WAITING_FOR_FOOD_NAME:
            user_data.temp_food_item['name'] = message_text
            user_data.current_context = WAITING_FOR_FOOD_CATEGORY
            
            # Suggerisci categorie comuni
            keyboard = [
                [
                    InlineKeyboardButton("Frutta", callback_data="category:Frutta"),
                    InlineKeyboardButton("Verdura", callback_data="category:Verdura")
                ],
                [
                    InlineKeyboardButton("Carne", callback_data="category:Carne"),
                    InlineKeyboardButton("Pesce", callback_data="category:Pesce")
                ],
                [
                    InlineKeyboardButton("Latticini", callback_data="category:Latticini"),
                    InlineKeyboardButton("Cereali", callback_data="category:Cereali")
                ],
                [
                    InlineKeyboardButton("Altro", callback_data="category:Altro")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "📋 Seleziona la categoria o inseriscine una personalizzata:",
                reply_markup=reply_markup
            )
            
        elif current_context == WAITING_FOR_FOOD_CATEGORY:
            user_data.temp_food_item['category'] = message_text
            user_data.current_context = WAITING_FOR_FOOD_QUANTITY
            
            await update.message.reply_text(
                "🔢 Inserisci la quantità (es. 1, 2.5, ecc.):"
            )
            
        elif current_context == WAITING_FOR_FOOD_QUANTITY:
            try:
                quantity = float(message_text.replace(',', '.'))
                user_data.temp_food_item['quantity'] = quantity
                user_data.current_context = WAITING_FOR_FOOD_UNIT
                
                # Suggerisci unità comuni
                keyboard = [
                    [
                        InlineKeyboardButton("g", callback_data="unit:g"),
                        InlineKeyboardButton("kg", callback_data="unit:kg")
                    ],
                    [
                        InlineKeyboardButton("ml", callback_data="unit:ml"),
                        InlineKeyboardButton("L", callback_data="unit:L")
                    ],
                    [
                        InlineKeyboardButton("pz", callback_data="unit:pz"),
                        InlineKeyboardButton("conf", callback_data="unit:conf")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "📏 Seleziona l'unità di misura o inseriscine una personalizzata:",
                    reply_markup=reply_markup
                )
                
            except ValueError:
                await update.message.reply_text(
                    "❌ Valore non valido. Inserisci un numero per la quantità (es. 1, 2.5, ecc.):"
                )
                
        elif current_context == WAITING_FOR_FOOD_UNIT:
            user_data.temp_food_item['unit'] = message_text
            user_data.current_context = WAITING_FOR_FOOD_EXPIRY
            
            # Calcola la data tra un mese come suggerimento
            one_month_later = datetime.datetime.now() + datetime.timedelta(days=30)
            suggested_date = one_month_later.strftime(DISPLAY_DATE_FORMAT)
            
            keyboard = [
                [
                    InlineKeyboardButton("Oggi", callback_data=f"expiry:{datetime.datetime.now().strftime(DATE_FORMAT)}")
                ],
                [
                    InlineKeyboardButton("+7 giorni", callback_data=f"expiry:{(datetime.datetime.now() + datetime.timedelta(days=7)).strftime(DATE_FORMAT)}")
                ],
                [
                    InlineKeyboardButton("+30 giorni", callback_data=f"expiry:{(datetime.datetime.now() + datetime.timedelta(days=30)).strftime(DATE_FORMAT)}")
                ],
                [
                    InlineKeyboardButton("Non scade", callback_data="expiry:none")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"📅 Inserisci la data di scadenza nel formato {DISPLAY_DATE_FORMAT} o seleziona un'opzione:",
                reply_markup=reply_markup
            )
            
        elif current_context == WAITING_FOR_FOOD_EXPIRY:
            # Converti la data nel formato corretto
            try:
                # Prova prima il formato visualizzato
                expiry_date = datetime.datetime.strptime(message_text, DISPLAY_DATE_FORMAT).strftime(DATE_FORMAT)
            except ValueError:
                try:
                    # Prova anche il formato del database
                    expiry_date = datetime.datetime.strptime(message_text, DATE_FORMAT).strftime(DATE_FORMAT)
                except ValueError:
                    await update.message.reply_text(
                        f"❌ Formato data non valido. Inserisci la data nel formato {DISPLAY_DATE_FORMAT}:"
                    )
                    return
            
            user_data.temp_food_item['expiry_date'] = expiry_date
            
            # Salva l'elemento nel database
            item_id = self.data_manager.add_food_item(
                user_id=user_id,
                name=user_data.temp_food_item['name'],
                category=user_data.temp_food_item['category'],
                quantity=user_data.temp_food_item['quantity'],
                unit=user_data.temp_food_item['unit'],
                expiry_date=user_data.temp_food_item['expiry_date'],
                notes=user_data.temp_food_item.get('notes')
            )
            
            if item_id:
                await update.message.reply_text(
                    f"✅ Elemento aggiunto all'inventario:\n\n"
                    f"- {user_data.temp_food_item['name']} ({user_data.temp_food_item['category']})\n"
                    f"- Quantità: {user_data.temp_food_item['quantity']} {user_data.temp_food_item['unit']}\n"
                    f"- Scadenza: {datetime.datetime.strptime(expiry_date, DATE_FORMAT).strftime(DISPLAY_DATE_FORMAT) if expiry_date != 'none' else 'Non scade'}"
                )
                
                # Chiedi se vuole aggiungere un altro elemento
                keyboard = [
                    [
                        InlineKeyboardButton("➕ Aggiungi altro", callback_data="inventory:add"),
                        InlineKeyboardButton("🔍 Visualizza inventario", callback_data="inventory:view")
                    ],
                    [
                        InlineKeyboardButton("🔙 Menu principale", callback_data="menu:back")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "Cosa vuoi fare ora?",
                    reply_markup=reply_markup
                )
                
                # Resetta i dati temporanei e il contesto
                user_data.temp_food_item = {}
                user_data.current_context = None
                
            else:
                await update.message.reply_text(
                    "❌ Si è verificato un errore durante l'aggiunta dell'elemento. Riprova più tardi."
                )
            
        # Gestisci gli altri stati in modo simile
        # ...
        
        else:
            # Invia il messaggio a Claude per un'elaborazione con AI
            await self.process_with_ai(update, context)
    
    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce i messaggi con foto.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
        """
        if not update.effective_user or not update.message or not update.message.photo:
            return
        
        user_id = update.effective_user.id
        
        # Controlla se l'utente è autorizzato
        if not self.is_allowed(user_id):
            return
        
        # Ottieni la foto con la risoluzione più alta
        photo = update.message.photo[-1]
        
        # Invia un messaggio di attesa
        await update.message.reply_text(
            "🔍 Sto analizzando l'immagine... Attendere prego."
        )
        
        # Ottieni il file dalla foto
        photo_file = await context.bot.get_file(photo.file_id)
        
        # Scarica la foto
        photo_bytes = await photo_file.download_as_bytearray()
        photo_stream = BytesIO(photo_bytes)
        
        # Ottieni la didascalia o usa un prompt predefinito
        caption = update.message.caption or "Analizza questa immagine e identificala."
        
        try:
            # Usa Claude Vision per analizzare l'immagine
            result = await self.anthropic.analyze_image(
                image_data=photo_stream,
                query=caption
            )
            
            # Invia la risposta
            await self.send_large_message(update.message.chat_id, result, context.bot)
            
        except ClaudeException as e:
            logger.error(f"Errore durante l'analisi dell'immagine: {str(e)}")
            await update.message.reply_text(
                f"❌ Si è verificato un errore durante l'analisi dell'immagine: {str(e)}"
            )
            
        except Exception as e:
            logger.error(f"Errore generico durante l'elaborazione dell'immagine: {str(e)}")
            await update.message.reply_text(
                "❌ Si è verificato un errore durante l'elaborazione dell'immagine. Riprova più tardi."
            )
    
    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce i messaggi con documenti.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
        """
        if not update.effective_user or not update.message or not update.message.document:
            return
        
        user_id = update.effective_user.id
        
        # Controlla se l'utente è autorizzato
        if not self.is_allowed(user_id):
            return
        
        document = update.message.document
        
        # Verifica se è un file JSON (per importazione dati)
        if document.mime_type == 'application/json' and document.file_name.endswith('.json'):
            await update.message.reply_text(
                "📁 Ricevuto file JSON. Verifico se è un file di importazione dati..."
            )
            
            # Scarica il documento
            document_file = await context.bot.get_file(document.file_id)
            
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                await document_file.download_to_drive(temp_file.name)
                
                try:
                    # Leggi il file JSON
                    with open(temp_file.name, 'r', encoding='utf-8') as f:
                        import_data = json.load(f)
                    
                    # Verifica se è un file di esportazione valido
                    if 'user_id' in import_data:
                        # Chiedi conferma prima di importare
                        keyboard = [
                            [
                                InlineKeyboardButton("✅ Sì, importa", callback_data=f"import:confirm:{temp_file.name}"),
                                InlineKeyboardButton("❌ No, annulla", callback_data="import:cancel")
                            ]
                        ]
                        
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        
                        await update.message.reply_text(
                            "⚠️ Stai per importare dati nel tuo profilo. "
                            "Questa operazione sovrascriverà i dati esistenti. Vuoi continuare?",
                            reply_markup=reply_markup
                        )
                        
                    else:
                        os.unlink(temp_file.name)
                        await update.message.reply_text(
                            "❌ Il file JSON non sembra essere un file di esportazione valido."
                        )
                        
                except json.JSONDecodeError:
                    os.unlink(temp_file.name)
                    await update.message.reply_text(
                        "❌ Il file non è un JSON valido."
                    )
                    
                except Exception as e:
                    os.unlink(temp_file.name)
                    logger.error(f"Errore durante l'elaborazione del file JSON: {str(e)}")
                    await update.message.reply_text(
                        f"❌ Si è verificato un errore durante l'elaborazione del file: {str(e)}"
                    )
                    
        else:
            # Per altri tipi di documenti, invia un messaggio generico
            await update.message.reply_text(
                f"📁 Ricevuto documento: {document.file_name}\n\n"
                f"Per importare dati, invia un file JSON di esportazione."
            )
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce le callback dei pulsanti inline.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
        """
        if not update.effective_user or not update.callback_query:
            return
        
        user_id = update.effective_user.id
        callback_data = update.callback_query.data
        
        # Controlla se l'utente è autorizzato
        if not self.is_allowed(user_id):
            await update.callback_query.answer("Non sei autorizzato a utilizzare questo bot.")
            return
        
        # Conferma la ricezione del callback
        await update.callback_query.answer()
        
        # Elabora il callback in base al prefisso
        if callback_data.startswith("menu:"):
            await self.handle_menu_callback(update, context, callback_data[5:])
            
        elif callback_data.startswith("inventory:"):
            await self.handle_inventory_callback(update, context, callback_data[10:])
            
        elif callback_data.startswith("meal:"):
            await self.handle_meal_callback(update, context, callback_data[5:])
            
        elif callback_data.startswith("shop:"):
            await self.handle_shopping_callback(update, context, callback_data[5:])
            
        elif callback_data.startswith("health:"):
            await self.handle_health_callback(update, context, callback_data[7:])
            
        elif callback_data.startswith("setting:"):
            await self.handle_setting_callback(update, context, callback_data[8:])
            
        elif callback_data.startswith("list:"):
            await self.handle_list_callback(update, context, callback_data[5:])
            
        elif callback_data.startswith("complete:"):
            await self.handle_complete_callback(update, context, callback_data[9:])
            
        elif callback_data.startswith("delete:"):
            await self.handle_delete_callback(update, context, callback_data[7:])
            
        elif callback_data.startswith("page:"):
            await self.handle_pagination_callback(update, context, callback_data[5:])
            
        elif callback_data.startswith("confirm:"):
            await self.handle_confirmation_callback(update, context, callback_data[8:])
            
        elif callback_data.startswith("cancel:"):
            await self.handle_cancel_callback(update, context, callback_data[7:])
            
        elif callback_data.startswith("category:"):
            # Gestione callback per la selezione della categoria
            category = callback_data[9:]
            user_data = self.get_user_data(user_id)
            
            if user_data.current_context == WAITING_FOR_FOOD_CATEGORY:
                user_data.temp_food_item['category'] = category
                user_data.current_context = WAITING_FOR_FOOD_QUANTITY
                
                await update.callback_query.edit_message_text(
                    f"📋 Categoria selezionata: {category}\n\n"
                    f"🔢 Inserisci la quantità (es. 1, 2.5, ecc.):"
                )
                
        elif callback_data.startswith("unit:"):
            # Gestione callback per la selezione dell'unità
            unit = callback_data[5:]
            user_data = self.get_user_data(user_id)
            
            if user_data.current_context == WAITING_FOR_FOOD_UNIT:
                user_data.temp_food_item['unit'] = unit
                user_data.current_context = WAITING_FOR_FOOD_EXPIRY
                
                # Suggerisci date di scadenza
                keyboard = [
                    [
                        InlineKeyboardButton("Oggi", callback_data=f"expiry:{datetime.datetime.now().strftime(DATE_FORMAT)}")
                    ],
                    [
                        InlineKeyboardButton("+7 giorni", callback_data=f"expiry:{(datetime.datetime.now() + datetime.timedelta(days=7)).strftime(DATE_FORMAT)}")
                    ],
                    [
                        InlineKeyboardButton("+30 giorni", callback_data=f"expiry:{(datetime.datetime.now() + datetime.timedelta(days=30)).strftime(DATE_FORMAT)}")
                    ],
                    [
                        InlineKeyboardButton("Non scade", callback_data="expiry:none")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    f"📏 Unità selezionata: {unit}\n\n"
                    f"📅 Inserisci la data di scadenza nel formato {DISPLAY_DATE_FORMAT} o seleziona un'opzione:",
                    reply_markup=reply_markup
                )
                
        elif callback_data.startswith("expiry:"):
            # Gestione callback per la selezione della data di scadenza
            expiry = callback_data[7:]
            user_data = self.get_user_data(user_id)
            
            if user_data.current_context == WAITING_FOR_FOOD_EXPIRY:
                user_data.temp_food_item['expiry_date'] = None if expiry == "none" else expiry
                
                # Salva l'elemento nel database
                item_id = self.data_manager.add_food_item(
                    user_id=user_id,
                    name=user_data.temp_food_item['name'],
                    category=user_data.temp_food_item['category'],
                    quantity=user_data.temp_food_item['quantity'],
                    unit=user_data.temp_food_item['unit'],
                    expiry_date=user_data.temp_food_item['expiry_date'],
                    notes=user_data.temp_food_item.get('notes')
                )
                
                if item_id:
                    # Formatta la data di scadenza per la visualizzazione
                    expiry_display = "Non scade" if expiry == "none" else datetime.datetime.strptime(expiry, DATE_FORMAT).strftime(DISPLAY_DATE_FORMAT)
                    
                    # Crea la tastiera per le azioni successive
                    keyboard = [
                        [
                            InlineKeyboardButton("➕ Aggiungi altro", callback_data="inventory:add"),
                            InlineKeyboardButton("🔍 Visualizza inventario", callback_data="inventory:view")
                        ],
                        [
                            InlineKeyboardButton("🔙 Menu principale", callback_data="menu:back")
                        ]
                    ]
                    
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.callback_query.edit_message_text(
                        f"✅ Elemento aggiunto all'inventario:\n\n"
                        f"- {user_data.temp_food_item['name']} ({user_data.temp_food_item['category']})\n"
                        f"- Quantità: {user_data.temp_food_item['quantity']} {user_data.temp_food_item['unit']}\n"
                        f"- Scadenza: {expiry_display}\n\n"
                        f"Cosa vuoi fare ora?",
                        reply_markup=reply_markup
                    )
                    
                    # Resetta i dati temporanei e il contesto
                    user_data.temp_food_item = {}
                    user_data.current_context = None
                    
                else:
                    await update.callback_query.edit_message_text(
                        "❌ Si è verificato un errore durante l'aggiunta dell'elemento. Riprova più tardi."
                    )
                    
                    # Resetta i dati temporanei e il contesto
                    user_data.temp_food_item = {}
                    user_data.current_context = None
            
        elif callback_data.startswith("import:"):
            # Gestione callback per l'importazione dei dati
            action = callback_data[7:]
            
            if action.startswith("confirm:"):
                file_path = action[8:]
                
                try:
                    # Leggi il file JSON
                    with open(file_path, 'r', encoding='utf-8') as f:
                        import_data = json.load(f)
                    
                    # Modifica l'ID utente per assicurarsi che i dati siano associati all'utente corrente
                    import_data['user_id'] = user_id
                    
                    # Importa i dati
                    success = self.data_manager.import_user_data(import_data, overwrite=True)
                    
                    if success:
                        await update.callback_query.edit_message_text(
                            "✅ Dati importati con successo! Usa /menu per iniziare a utilizzare il tuo assistente."
                        )
                    else:
                        await update.callback_query.edit_message_text(
                            "❌ Si è verificato un errore durante l'importazione dei dati. Riprova più tardi."
                        )
                        
                except Exception as e:
                    logger.error(f"Errore durante l'importazione dei dati: {str(e)}")
                    await update.callback_query.edit_message_text(
                        f"❌ Si è verificato un errore durante l'importazione dei dati: {str(e)}"
                    )
                    
                finally:
                    # Elimina il file temporaneo
                    try:
                        os.unlink(file_path)
                    except Exception:
                        pass
                    
            elif action == "cancel":
                await update.callback_query.edit_message_text(
                    "❌ Importazione annullata."
                )
        
        else:
            # Callback non riconosciuto
            logger.warning(f"Callback non riconosciuto: {callback_data}")
    
    async def handle_menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
        """
        Gestisce i callback del menu principale.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            action: Azione da eseguire
        """
        if action == "inventory":
            await self.show_inventory_menu(update, context, edit=True)
            
        elif action == "meal_plans":
            await self.show_meal_plan_menu(update, context, edit=True)
            
        elif action == "shopping":
            await self.show_shopping_list_menu(update, context, edit=True)
            
        elif action == "health":
            await self.show_health_menu(update, context, edit=True)
            
        elif action == "settings":
            # Usa il comando settings per aggiornare il messaggio
            if update.callback_query.message:
                # Crea un finto update per il comando
                new_update = Update(
                    update_id=update.update_id,
                    message=update.callback_query.message
                )
                await self.command_settings(new_update, context)
                
        elif action == "help":
            # Usa il comando help per aggiornare il messaggio
            if update.callback_query.message:
                text = (
                    "🤖 *Guida all'Assistente Personale Claude*\n\n"
                    "*Comandi principali:*\n"
                    "/start - Avvia il bot\n"
                    "/menu - Mostra il menu principale\n"
                    "/help - Mostra questa guida\n"
                    "/settings - Gestisci le tue impostazioni\n"
                    "/reset - Resetta la conversazione corrente\n"
                    "/cancel - Annulla l'operazione corrente\n\n"
                    "Per tornare al menu principale, usa /menu."
                )
                
                keyboard = [[InlineKeyboardButton("🔙 Menu principale", callback_data="menu:back")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
                )
                
        elif action == "back":
            # Torna al menu principale
            keyboard = [
                [
                    InlineKeyboardButton("🍎 Inventario Alimentare", callback_data="menu:inventory"),
                    InlineKeyboardButton("🍽️ Piani Alimentari", callback_data="menu:meal_plans")
                ],
                [
                    InlineKeyboardButton("🛒 Lista della Spesa", callback_data="menu:shopping"),
                    InlineKeyboardButton("❤️ Monitoraggio Sanitario", callback_data="menu:health")
                ],
                [
                    InlineKeyboardButton("⚙️ Impostazioni", callback_data="menu:settings"),
                    InlineKeyboardButton("❓ Aiuto", callback_data="menu:help")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                "🔍 *Menu Principale*\n\n"
                "Seleziona una categoria per iniziare:",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def show_inventory_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        """
        Mostra il menu dell'inventario alimentare.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            edit: Se True, modifica il messaggio esistente invece di inviarne uno nuovo
        """
        keyboard = [
            [
                InlineKeyboardButton("➕ Aggiungi alimento", callback_data="inventory:add"),
                InlineKeyboardButton("🔍 Visualizza inventario", callback_data="inventory:view")
            ],
            [
                InlineKeyboardButton("⚠️ Alimenti in scadenza", callback_data="inventory:expiring"),
                InlineKeyboardButton("🗑️ Elimina alimento", callback_data="inventory:delete")
            ],
            [
                InlineKeyboardButton("🔍 Cerca per categoria", callback_data="inventory:search"),
                InlineKeyboardButton("📊 Statistiche inventario", callback_data="inventory:stats")
            ],
            [
                InlineKeyboardButton("🔙 Menu principale", callback_data="menu:back")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = (
            "🍎 *Menu Inventario Alimentare*\n\n"
            "Gestisci il tuo inventario di alimenti, tieni traccia delle scadenze "
            "e monitora le quantità disponibili."
        )
        
        if edit and update.callback_query and update.callback_query.message:
            await update.callback_query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
    
    async def handle_inventory_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
        """
        Gestisce i callback dell'inventario alimentare.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            action: Azione da eseguire
        """
        user_id = update.effective_user.id
        user_data = self.get_user_data(user_id)
        
        if action == "add":
            # Inizia il processo di aggiunta di un alimento
            user_data.temp_food_item = {}
            user_data.current_context = WAITING_FOR_FOOD_NAME
            
            await update.callback_query.edit_message_text(
                "➕ *Aggiungi Alimento*\n\n"
                "Inserisci il nome dell'alimento:",
                parse_mode=ParseMode.MARKDOWN
            )
            
        elif action == "view":
            # Visualizza l'inventario
            inventory = self.data_manager.get_food_inventory(user_id)
            
            if not inventory:
                # Inventario vuoto
                keyboard = [
                    [
                        InlineKeyboardButton("➕ Aggiungi alimento", callback_data="inventory:add"),
                        InlineKeyboardButton("🔙 Menu inventario", callback_data="menu:inventory")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    "🍎 *Inventario Alimentare*\n\n"
                    "Il tuo inventario è vuoto. Aggiungi alimenti per iniziare!",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                
            else:
                # Organizza l'inventario per categoria
                inventory_by_category = {}
                for item in inventory:
                    category = item['category']
                    if category not in inventory_by_category:
                        inventory_by_category[category] = []
                    inventory_by_category[category].append(item)
                
                # Crea il messaggio
                text = "🍎 *Inventario Alimentare*\n\n"
                
                for category, items in inventory_by_category.items():
                    text += f"*{category}*:\n"
                    
                    for item in items:
                        # Formatta la data di scadenza
                        expiry = "Non scade"
                        if item['expiry_date']:
                            expiry_date = datetime.datetime.strptime(item['expiry_date'], DATE_FORMAT)
                            expiry = expiry_date.strftime(DISPLAY_DATE_FORMAT)
                            
                            # Evidenzia se in scadenza (entro 3 giorni)
                            days_to_expiry = (expiry_date.date() - datetime.date.today()).days
                            if days_to_expiry <= 3 and days_to_expiry >= 0:
                                expiry = f"⚠️ {expiry} (tra {days_to_expiry} giorni)"
                            elif days_to_expiry < 0:
                                expiry = f"❌ {expiry} (scaduto)"
                        
                        text += f"- {item['name']}: {item['quantity']} {item['unit']} (Scad: {expiry})\n"
                    
                    text += "\n"
                
                # Verifica se il messaggio è troppo lungo
                if len(text) > MAX_MESSAGE_LENGTH:
                    # Se troppo lungo, dividi per categorie
                    await update.callback_query.edit_message_text(
                        "🍎 *Inventario Alimentare*\n\n"
                        "Il tuo inventario è molto ampio. Seleziona una categoria per visualizzarla:",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    
                    # Crea una tastiera con le categorie
                    keyboard = []
                    row = []
                    
                    for i, category in enumerate(inventory_by_category.keys()):
                        row.append(InlineKeyboardButton(category, callback_data=f"inventory:category:{category}"))
                        
                        # Massimo 2 bottoni per riga
                        if len(row) == 2 or i == len(inventory_by_category.keys()) - 1:
                            keyboard.append(row)
                            row = []
                    
                    # Aggiungi i pulsanti di navigazione
                    keyboard.append([
                        InlineKeyboardButton("➕ Aggiungi alimento", callback_data="inventory:add"),
                        InlineKeyboardButton("🔙 Menu inventario", callback_data="menu:inventory")
                    ])
                    
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.callback_query.edit_message_reply_markup(reply_markup)
                    
                else:
                    # Se non troppo lungo, mostra tutto
                    keyboard = [
                        [
                            InlineKeyboardButton("➕ Aggiungi alimento", callback_data="inventory:add"),
                            InlineKeyboardButton("🔍 Cerca per categoria", callback_data="inventory:search")
                        ],
                        [
                            InlineKeyboardButton("🔙 Menu inventario", callback_data="menu:inventory")
                        ]
                    ]
                    
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.callback_query.edit_message_text(
                        text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
                    )
                    
        elif action.startswith("category:"):
            # Visualizza l'inventario per categoria specifica
            category = action[9:]
            inventory = self.data_manager.get_food_inventory(user_id, category=category)
            
            text = f"🍎 *Inventario Alimentare - {category}*\n\n"
            
            if not inventory:
                text += f"Nessun elemento trovato nella categoria {category}."
            else:
                for item in inventory:
                    # Formatta la data di scadenza
                    expiry = "Non scade"
                    if item['expiry_date']:
                        expiry_date = datetime.datetime.strptime(item['expiry_date'], DATE_FORMAT)
                        expiry = expiry_date.strftime(DISPLAY_DATE_FORMAT)
                        
                        # Evidenzia se in scadenza (entro 3 giorni)
                        days_to_expiry = (expiry_date.date() - datetime.date.today()).days
                        if days_to_expiry <= 3 and days_to_expiry >= 0:
                            expiry = f"⚠️ {expiry} (tra {days_to_expiry} giorni)"
                        elif days_to_expiry < 0:
                            expiry = f"❌ {expiry} (scaduto)"
                    
                    text += f"- {item['name']}: {item['quantity']} {item['unit']} (Scad: {expiry})\n"
            
            keyboard = [
                [
                    InlineKeyboardButton("🔍 Tutte le categorie", callback_data="inventory:view"),
                    InlineKeyboardButton("🔙 Menu inventario", callback_data="menu:inventory")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
            
        elif action == "expiring":
            # Visualizza gli alimenti in scadenza (entro 7 giorni)
            inventory = self.data_manager.get_food_inventory(user_id, expiring_soon=True, days_threshold=7)
            
            text = "⚠️ *Alimenti in Scadenza*\n\n"
            
            if not inventory:
                text += "Non hai alimenti in scadenza nei prossimi 7 giorni."
            else:
                # Ordina per data di scadenza
                inventory.sort(key=lambda x: x['expiry_date'] or "9999-12-31")
                
                for item in inventory:
                    # Formatta la data di scadenza
                    if item['expiry_date']:
                        expiry_date = datetime.datetime.strptime(item['expiry_date'], DATE_FORMAT)
                        expiry = expiry_date.strftime(DISPLAY_DATE_FORMAT)
                        
                        # Calcola i giorni rimanenti
                        days_to_expiry = (expiry_date.date() - datetime.date.today()).days
                        
                        if days_to_expiry < 0:
                            expiry_info = f"❌ Scaduto da {abs(days_to_expiry)} giorni"
                        elif days_to_expiry == 0:
                            expiry_info = "⚠️ Scade oggi"
                        else:
                            expiry_info = f"⚠️ Scade tra {days_to_expiry} giorni"
                        
                        text += f"- {item['name']} ({item['category']}): {item['quantity']} {item['unit']}\n"
                        text += f"  {expiry_info} ({expiry})\n"
            
            keyboard = [
                [
                    InlineKeyboardButton("🔍 Visualizza tutto", callback_data="inventory:view"),
                    InlineKeyboardButton("🔙 Menu inventario", callback_data="menu:inventory")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
            
        elif action == "delete":
            # Mostra la lista degli alimenti per l'eliminazione
            inventory = self.data_manager.get_food_inventory(user_id)
            
            if not inventory:
                # Inventario vuoto
                keyboard = [
                    [
                        InlineKeyboardButton("➕ Aggiungi alimento", callback_data="inventory:add"),
                        InlineKeyboardButton("🔙 Menu inventario", callback_data="menu:inventory")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    "🍎 *Elimina Alimento*\n\n"
                    "Il tuo inventario è vuoto. Non ci sono alimenti da eliminare.",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                
            else:
                # Crea la tastiera con gli alimenti
                keyboard = []
                
                for item in inventory[:8]:  # Limita a 8 elementi per non superare i limiti di Telegram
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{item['name']} ({item['quantity']} {item['unit']})",
                            callback_data=f"delete:food:{item['id']}"
                        )
                    ])
                
                # Aggiungi i pulsanti di navigazione
                keyboard.append([
                    InlineKeyboardButton("🔙 Menu inventario", callback_data="menu:inventory")
                ])
                
                # Se ci sono più di 8 elementi, aggiungi pulsante per altri
                if len(inventory) > 8:
                    keyboard.append([
                        InlineKeyboardButton("➡️ Altri elementi", callback_data="inventory:delete:next")
                    ])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    "🗑️ *Elimina Alimento*\n\n"
                    "Seleziona l'alimento da eliminare:",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                
        elif action == "search":
            # Mostra le categorie per la ricerca
            inventory = self.data_manager.get_food_inventory(user_id)
            
            if not inventory:
                # Inventario vuoto
                keyboard = [
                    [
                        InlineKeyboardButton("➕ Aggiungi alimento", callback_data="inventory:add"),
                        InlineKeyboardButton("🔙 Menu inventario", callback_data="menu:inventory")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    "🔍 *Cerca per Categoria*\n\n"
                    "Il tuo inventario è vuoto. Aggiungi alimenti per iniziare!",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                
            else:
                # Ottieni tutte le categorie uniche
                categories = set(item['category'] for item in inventory)
                
                # Crea la tastiera con le categorie
                keyboard = []
                row = []
                
                for i, category in enumerate(categories):
                    row.append(InlineKeyboardButton(category, callback_data=f"inventory:category:{category}"))
                    
                    # Massimo 2 bottoni per riga
                    if len(row) == 2 or i == len(categories) - 1:
                        keyboard.append(row)
                        row = []
                
                # Aggiungi i pulsanti di navigazione
                keyboard.append([
                    InlineKeyboardButton("🔍 Visualizza tutto", callback_data="inventory:view"),
                    InlineKeyboardButton("🔙 Menu inventario", callback_data="menu:inventory")
                ])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    "🔍 *Cerca per Categoria*\n\n"
                    "Seleziona una categoria da visualizzare:",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                
        elif action == "stats":
            # Mostra statistiche dell'inventario
            inventory = self.data_manager.get_food_inventory(user_id)
            
            if not inventory:
                # Inventario vuoto
                keyboard = [
                    [
                        InlineKeyboardButton("➕ Aggiungi alimento", callback_data="inventory:add"),
                        InlineKeyboardButton("🔙 Menu inventario", callback_data="menu:inventory")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    "📊 *Statistiche Inventario*\n\n"
                    "Il tuo inventario è vuoto. Aggiungi alimenti per visualizzare le statistiche!",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                
            else:
                # Calcola statistiche
                total_items = len(inventory)
                categories = {}
                expiring_soon = 0
                expired = 0
                
                today = datetime.date.today()
                
                for item in inventory:
                    # Conta per categoria
                    category = item['category']
                    if category not in categories:
                        categories[category] = 0
                    categories[category] += 1
                    
                    # Conta scadenze
                    if item['expiry_date']:
                        expiry_date = datetime.datetime.strptime(item['expiry_date'], DATE_FORMAT).date()
                        days_to_expiry = (expiry_date - today).days
                        
                        if days_to_expiry < 0:
                            expired += 1
                        elif days_to_expiry <= 7:
                            expiring_soon += 1
                
                # Crea il messaggio
                text = (
                    "📊 *Statistiche Inventario*\n\n"
                    f"📦 Totale elementi: {total_items}\n"
                    f"🏷️ Categorie: {len(categories)}\n"
                    f"⚠️ In scadenza (7 giorni): {expiring_soon}\n"
                    f"❌ Scaduti: {expired}\n\n"
                    
                    "*Distribuzione per categoria:*\n"
                )
                
                # Aggiungi distribuzione per categoria
                for category, count in categories.items():
                    percentage = round((count / total_items) * 100)
                    text += f"- {category}: {count} ({percentage}%)\n"
                
                keyboard = [
                    [
                        InlineKeyboardButton("⚠️ Alimenti in scadenza", callback_data="inventory:expiring"),
                        InlineKeyboardButton("🔍 Visualizza inventario", callback_data="inventory:view")
                    ],
                    [
                        InlineKeyboardButton("🔙 Menu inventario", callback_data="menu:inventory")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
                )
    
    async def handle_delete_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
        """
        Gestisce i callback di eliminazione.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            action: Azione da eseguire
        """
        user_id = update.effective_user.id
        
        if action.startswith("food:"):
            # Elimina un alimento dall'inventario
            item_id = int(action[5:])
            
            # Ottieni i dettagli dell'elemento prima di eliminarlo
            item = self.data_manager.get_food_item(item_id)
            
            if not item:
                await update.callback_query.edit_message_text(
                    "❌ Elemento non trovato. Potrebbe essere stato già eliminato."
                )
                return
            
            # Chiedi conferma
            keyboard = [
                [
                    InlineKeyboardButton("✅ Conferma eliminazione", callback_data=f"confirm:delete_food:{item_id}"),
                    InlineKeyboardButton("❌ Annulla", callback_data="inventory:delete")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Formatta la data di scadenza
            expiry = "Non scade"
            if item['expiry_date']:
                expiry_date = datetime.datetime.strptime(item['expiry_date'], DATE_FORMAT)
                expiry = expiry_date.strftime(DISPLAY_DATE_FORMAT)
            
            await update.callback_query.edit_message_text(
                f"⚠️ *Conferma Eliminazione*\n\n"
                f"Sei sicuro di voler eliminare questo elemento?\n\n"
                f"- {item['name']} ({item['category']})\n"
                f"- Quantità: {item['quantity']} {item['unit']}\n"
                f"- Scadenza: {expiry}",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def handle_confirmation_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
        """
        Gestisce i callback di conferma.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            action: Azione da eseguire
        """
        user_id = update.effective_user.id
        
        if action.startswith("delete_food:"):
            # Conferma eliminazione alimento
            item_id = int(action[12:])
            
            # Elimina l'elemento
            success = self.data_manager.delete_food_item(item_id)
            
            if success:
                keyboard = [
                    [
                        InlineKeyboardButton("🔍 Visualizza inventario", callback_data="inventory:view"),
                        InlineKeyboardButton("🔙 Menu inventario", callback_data="menu:inventory")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    "✅ Elemento eliminato con successo!",
                    reply_markup=reply_markup
                )
                
            else:
                keyboard = [
                    [
                        InlineKeyboardButton("↩️ Riprova", callback_data="inventory:delete"),
                        InlineKeyboardButton("🔙 Menu inventario", callback_data="menu:inventory")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    "❌ Si è verificato un errore durante l'eliminazione dell'elemento. Riprova più tardi.",
                    reply_markup=reply_markup
                )
    
    async def handle_cancel_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
        """
        Gestisce i callback di annullamento.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            action: Azione da eseguire
        """
        # Implementa la gestione dei callback di annullamento
        pass
    
    # ... Altre implementazioni di handler per meal_plan, shopping_list, health_tracker, ecc.
    
    async def show_meal_plan_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        """
        Mostra il menu dei piani alimentari.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            edit: Se True, modifica il messaggio esistente invece di inviarne uno nuovo
        """
        # Implementa la visualizzazione del menu dei piani alimentari
        pass
    
    async def show_shopping_list_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        """
        Mostra il menu delle liste della spesa.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            edit: Se True, modifica il messaggio esistente invece di inviarne uno nuovo
        """
        # Implementa la visualizzazione del menu delle liste della spesa
        pass
    
    async def show_health_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        """
        Mostra il menu del monitoraggio sanitario.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            edit: Se True, modifica il messaggio esistente invece di inviarne uno nuovo
        """
        # Implementa la visualizzazione del menu del monitoraggio sanitario
        pass
    
    async def handle_meal_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
        """
        Gestisce i callback dei piani alimentari.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            action: Azione da eseguire
        """
        # Implementa la gestione dei callback dei piani alimentari
        pass
    
    async def handle_shopping_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
        """
        Gestisce i callback delle liste della spesa.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            action: Azione da eseguire
        """
        # Implementa la gestione dei callback delle liste della spesa
        pass
    
    async def handle_health_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
        """
        Gestisce i callback del monitoraggio sanitario.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            action: Azione da eseguire
        """
        # Implementa la gestione dei callback del monitoraggio sanitario
        pass
    
    async def handle_setting_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
        """
        Gestisce i callback delle impostazioni.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            action: Azione da eseguire
        """
        # Implementa la gestione dei callback delle impostazioni
        pass
    
    async def handle_list_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
        """
        Gestisce i callback delle liste.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            action: Azione da eseguire
        """
        # Implementa la gestione dei callback delle liste
        pass
    
    async def handle_complete_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
        """
        Gestisce i callback di completamento.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            action: Azione da eseguire
        """
        user_id = update.effective_user.id
        
        if action.startswith("shopping_item:"):
            # Completa un elemento della lista della spesa
            item_id = int(action[13:])
            
            # Aggiorna lo stato di completamento
            success = self.data_manager.mark_shopping_item_as_completed(item_id, completed=True)
            
            if success:
                # Ottieni l'ID della lista per aggiornare la vista
                item = self.data_manager.get_shopping_item(item_id)
                list_id = item['list_id'] if item else None
                
                if list_id:
                    # Aggiorna la vista della lista
                    await self.show_shopping_list_items(update, context, list_id)
                else:
                    await update.callback_query.edit_message_text(
                        "✅ Elemento completato con successo!",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔙 Menu liste della spesa", callback_data="menu:shopping")
                        ]])
                    )
            else:
                await update.callback_query.edit_message_text(
                    "❌ Si è verificato un errore durante l'aggiornamento dell'elemento. Riprova più tardi.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Menu liste della spesa", callback_data="menu:shopping")
                    ]])
                )
    
    async def handle_pagination_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
        """
        Gestisce i callback di paginazione.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            action: Azione da eseguire
        """
        user_id = update.effective_user.id
        user_data = self.get_user_data(user_id)
        
        # Formato del callback: "page:tipo:id:pagina"
        parts = action.split(":")
        if len(parts) < 3:
            return
        
        page_type = parts[0]
        entity_id = parts[1]
        page = int(parts[2])
        
        if page_type == "inventory":
            # Paginazione dell'inventario
            inventory = self.data_manager.get_food_inventory(user_id)
            
            # Calcola gli indici di inizio e fine
            start_idx = page * user_data.items_per_page
            end_idx = start_idx + user_data.items_per_page
            
            # Ottieni la pagina corrente
            current_page_items = inventory[start_idx:end_idx]
            
            # Crea il messaggio
            text = "🍎 *Inventario Alimentare*\n\n"
            
            for item in current_page_items:
                # Formatta la data di scadenza
                expiry = "Non scade"
                if item['expiry_date']:
                    expiry_date = datetime.datetime.strptime(item['expiry_date'], DATE_FORMAT)
                    expiry = expiry_date.strftime(DISPLAY_DATE_FORMAT)
                
                text += f"- {item['name']} ({item['category']}): {item['quantity']} {item['unit']} (Scad: {expiry})\n"
            
            # Crea la tastiera con i pulsanti di navigazione
            keyboard = []
            
            # Pulsanti di paginazione
            pagination_row = []
            
            if page > 0:
                pagination_row.append(InlineKeyboardButton("⬅️ Precedente", callback_data=f"page:inventory:{entity_id}:{page-1}"))
            
            if end_idx < len(inventory):
                pagination_row.append(InlineKeyboardButton("➡️ Successiva", callback_data=f"page:inventory:{entity_id}:{page+1}"))
            
            if pagination_row:
                keyboard.append(pagination_row)
            
            # Pulsanti di azione
            keyboard.append([
                InlineKeyboardButton("➕ Aggiungi alimento", callback_data="inventory:add"),
                InlineKeyboardButton("🔙 Menu inventario", callback_data="menu:inventory")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
        
        elif page_type == "shopping":
            # Paginazione della lista della spesa
            # Implementazione simile all'inventario
            pass
    
    async def process_with_ai(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Elabora un messaggio con l'AI di Claude.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
        """
        if not update.effective_user or not update.message or not update.message.text:
            return
        
        user_id = update.effective_user.id
        message_text = update.message.text
        
        # Ottieni i dati dell'utente
        user_data = self.get_user_data(user_id)
        
        # Invia un messaggio di attesa
        waiting_message = await update.message.reply_text(
            "🤔 Sto elaborando la tua richiesta..."
        )
        
        try:
            # Aggiorna la cronologia delle conversazioni
            current_time = datetime.datetime.now()
            
            # Resetta la cronologia se è passato troppo tempo dall'ultima interazione
            if (current_time - user_data.last_interaction_time).total_seconds() > 30 * 60:  # 30 minuti
                user_data.conversation_history = []
            
            user_data.last_interaction_time = current_time
            
            # Aggiungi il messaggio utente alla cronologia
            user_data.conversation_history.append({"role": "user", "content": message_text})
            
            # Prepara il contesto per Claude
            # Ottieni informazioni utente dal database
            user_preferences = self.data_manager.get_all_user_preferences(user_id)
            health_conditions = self.data_manager.get_health_conditions(user_id)
            dietary_restrictions = self.data_manager.get_dietary_restrictions(user_id)
            
            # Crea un prompt di sistema personalizzato
            system_prompt = (
                "Sei Claude, un assistente personale specializzato in nutrizione, piani alimentari e salute. "
                "Aiuti l'utente a gestire il proprio inventario alimentare, creare piani alimentari, "
                "generare liste della spesa e monitorare la propria salute."
            )
            
            # Aggiungi informazioni sanitarie se disponibili
            if health_conditions or dietary_restrictions:
                system_prompt += "\n\nInformazioni sanitarie dell'utente:"
                
                if health_conditions:
                    system_prompt += "\nCondizioni mediche:"
                    for condition in health_conditions:
                        system_prompt += f"\n- {condition['name']}"
                        if condition.get('description'):
                            system_prompt += f": {condition['description']}"
                
                if dietary_restrictions:
                    system_prompt += "\nRestrizioni alimentari:"
                    for restriction in dietary_restrictions:
                        system_prompt += f"\n- {restriction['name']} ({restriction['food_type']})"
                        if restriction.get('reason'):
                            system_prompt += f": {restriction['reason']}"
            
            # Chiama l'API di Claude
            response = await self.anthropic.simple_query(
                text=message_text,
                system=system_prompt,
                conversation_history=user_data.conversation_history[-5:] if len(user_data.conversation_history) > 1 else None
            )
            
            # Aggiungi la risposta alla cronologia
            user_data.conversation_history.append({"role": "assistant", "content": response})
            
            # Elimina il messaggio di attesa
            await context.bot.delete_message(
                chat_id=update.message.chat_id,
                message_id=waiting_message.message_id
            )
            
            # Invia la risposta
            await self.send_large_message(update.message.chat_id, response, context.bot)
            
        except ClaudeException as e:
            logger.error(f"Errore durante l'elaborazione con Claude: {str(e)}")
            
            await context.bot.edit_message_text(
                chat_id=update.message.chat_id,
                message_id=waiting_message.message_id,
                text=f"❌ Si è verificato un errore durante l'elaborazione con Claude: {str(e)}"
            )
            
        except Exception as e:
            logger.error(f"Errore generico durante l'elaborazione del messaggio: {str(e)}")
            
            await context.bot.edit_message_text(
                chat_id=update.message.chat_id,
                message_id=waiting_message.message_id,
                text="❌ Si è verificato un errore durante l'elaborazione del messaggio. Riprova più tardi."
            )
    
    async def send_large_message(self, chat_id: int, text: str, bot: Bot):
        """
        Invia un messaggio grande dividendolo in più parti se necessario.
        
        Args:
            chat_id: ID della chat
            text: Testo da inviare
            bot: Istanza del bot Telegram
        """
        if len(text) <= MAX_MESSAGE_LENGTH:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            # Dividi il messaggio in parti più piccole
            parts = []
            for i in range(0, len(text), MAX_MESSAGE_LENGTH):
                parts.append(text[i:i + MAX_MESSAGE_LENGTH])
            
            # Invia ogni parte
            for part in parts:
                await bot.send_message(
                    chat_id=chat_id,
                    text=part,
                    parse_mode=ParseMode.MARKDOWN
                )
    
    async def show_shopping_list_items(self, update: Update, context: ContextTypes.DEFAULT_TYPE, list_id: int):
        """
        Mostra gli elementi di una lista della spesa.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            list_id: ID della lista della spesa
        """
        user_id = update.effective_user.id
        
        # Ottieni gli elementi della lista
        items = self.data_manager.get_shopping_list_items(list_id, include_completed=True)
        
        if not items:
            # Lista vuota
            keyboard = [
                [
                    InlineKeyboardButton("➕ Aggiungi articolo", callback_data=f"shop:add_item:{list_id}"),
                    InlineKeyboardButton("🔙 Menu liste", callback_data="menu:shopping")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                "🛒 *Lista della Spesa*\n\n"
                "Questa lista è vuota. Aggiungi articoli per iniziare!",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
        else:
            # Organizza gli elementi per categoria
            items_by_category = {}
            for item in items:
                category = item['category'] or "Altro"
                if category not in items_by_category:
                    items_by_category[category] = []
                items_by_category[category].append(item)
            
            # Crea il messaggio
            text = "🛒 *Lista della Spesa*\n\n"
            
            for category, cat_items in items_by_category.items():
                text += f"*{category}*:\n"
                
                for item in cat_items:
                    # Formatta l'elemento
                    check = "✅ " if item['completed'] else "☐ "
                    quantity_text = f" ({item['quantity']} {item['unit']})" if item['quantity'] and item['unit'] else ""
                    
                    text += f"{check}{item['name']}{quantity_text}\n"
                
                text += "\n"
            
            # Crea la tastiera
            keyboard = []
            
            # Pulsanti per gli elementi da completare
            incomplete_items = [item for item in items if not item['completed']]
            
            if incomplete_items:
                keyboard.append([
                    InlineKeyboardButton("✅ Segna tutti come completati", callback_data=f"shop:complete_all:{list_id}")
                ])
                
                # Mostra fino a 5 elementi non completati per la selezione rapida
                for item in incomplete_items[:5]:
                    keyboard.append([
                        InlineKeyboardButton(
                            f"✅ {item['name']}",
                            callback_data=f"complete:shopping_item:{item['id']}"
                        )
                    ])
            
            # Pulsanti di azione
            keyboard.append([
                InlineKeyboardButton("➕ Aggiungi articolo", callback_data=f"shop:add_item:{list_id}"),
                InlineKeyboardButton("🔄 Aggiorna", callback_data=f"shop:view_list:{list_id}")
            ])
            
            keyboard.append([
                InlineKeyboardButton("🔙 Menu liste", callback_data="menu:shopping")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Verifica se il messaggio è troppo lungo
            if len(text) > MAX_MESSAGE_LENGTH:
                # Dividi in più messaggi
                await self.send_large_message(update.callback_query.message.chat_id, text, context.bot)
                
                # Invia un messaggio separato con i pulsanti
                await update.callback_query.message.reply_text(
                    "Azioni disponibili:",
                    reply_markup=reply_markup
                )
                
            else:
                # Invia un unico messaggio
                await update.callback_query.edit_message_text(
                    text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
                )
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce gli errori durante l'esecuzione.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
        """
        # Estrai l'eccezione
        error = context.error
        
        # Registra l'errore
        logger.error(f"Errore durante l'elaborazione dell'update: {str(error)}")
        logger.error(f"Update: {update}")
        
        # Messaggi di errore da mostrare all'utente
        error_message = "Si è verificato un errore. Riprova più tardi."
        
        # Determina il tipo di errore per messaggi più precisi
        if isinstance(error, ClaudeException):
            error_message = f"Errore durante la comunicazione con Claude: {str(error)}"
        elif "Forbidden" in str(error):
            error_message = "Non ho i permessi necessari per eseguire questa azione."
        elif "Timed out" in str(error):
            error_message = "La richiesta è scaduta. La rete potrebbe essere lenta."
        elif "Message is not modified" in str(error):
            # Ignora questo errore
            return
        
        # Invia il messaggio di errore
        try:
            if update and hasattr(update, 'effective_message') and update.effective_message:
                await update.effective_message.reply_text(
                    f"❌ {error_message}"
                )
            elif update and hasattr(update, 'callback_query') and update.callback_query:
                await update.callback_query.answer(
                    f"❌ {error_message}"
                )
        except Exception as e:
            logger.error(f"Impossibile inviare il messaggio di errore: {str(e)}")
            
        # Se in modalità debug, registra il traceback completo
        if self.debug_mode:
            import traceback
            logger.error(traceback.format_exc())
    
    # Implementazione del menu dei piani alimentari
    async def show_meal_plan_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        """
        Mostra il menu dei piani alimentari.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            edit: Se True, modifica il messaggio esistente invece di inviarne uno nuovo
        """
        user_id = update.effective_user.id
        
        # Crea la tastiera inline per il menu
        keyboard = [
            [
                InlineKeyboardButton("➕ Crea piano alimentare", callback_data="meal:create"),
                InlineKeyboardButton("🔍 Visualizza piani", callback_data="meal:view_plans")
            ],
            [
                InlineKeyboardButton("📆 Piano di oggi", callback_data="meal:today"),
                InlineKeyboardButton("📊 Statistiche nutrizionali", callback_data="meal:stats")
            ],
            [
                InlineKeyboardButton("🔙 Menu principale", callback_data="menu:back")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = (
            "🍽️ *Menu Piani Alimentari*\n\n"
            "Crea e gestisci i tuoi piani alimentari, visualizza i pasti programmati "
            "e monitora il tuo apporto nutrizionale."
        )
        
        if edit and update.callback_query and update.callback_query.message:
            await update.callback_query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
    
    # Implementazione del menu delle liste della spesa
    async def show_shopping_list_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        """
        Mostra il menu delle liste della spesa.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            edit: Se True, modifica il messaggio esistente invece di inviarne uno nuovo
        """
        user_id = update.effective_user.id
        
        # Ottieni tutte le liste della spesa dell'utente
        shopping_lists = self.data_manager.get_shopping_lists(user_id)
        
        # Crea la tastiera inline per il menu
        keyboard = [
            [
                InlineKeyboardButton("➕ Crea nuova lista", callback_data="shop:create")
            ]
        ]
        
        # Aggiungi le liste esistenti se presenti
        if shopping_lists:
            # Mostra solo le prime 5 liste per non superare i limiti di Telegram
            for shopping_list in shopping_lists[:5]:
                keyboard.append([
                    InlineKeyboardButton(
                        f"📋 {shopping_list['name']}",
                        callback_data=f"shop:view_list:{shopping_list['id']}"
                    )
                ])
            
            # Se ci sono più di 5 liste, aggiungi un pulsante per visualizzare tutte
            if len(shopping_lists) > 5:
                keyboard.append([
                    InlineKeyboardButton("🔍 Visualizza tutte le liste", callback_data="shop:view_all")
                ])
        
        # Aggiungi opzioni aggiuntive
        keyboard.append([
            InlineKeyboardButton("🔄 Genera da inventario", callback_data="shop:generate")
        ])
        
        keyboard.append([
            InlineKeyboardButton("🔙 Menu principale", callback_data="menu:back")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = (
            "🛒 *Menu Liste della Spesa*\n\n"
            "Crea e gestisci le tue liste della spesa, aggiungi articoli "
            "e tieni traccia degli acquisti."
        )
        
        if edit and update.callback_query and update.callback_query.message:
            await update.callback_query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
    
    # Implementazione del menu del monitoraggio sanitario
    async def show_health_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        """
        Mostra il menu del monitoraggio sanitario.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            edit: Se True, modifica il messaggio esistente invece di inviarne uno nuovo
        """
        user_id = update.effective_user.id
        
        # Crea la tastiera inline per il menu
        keyboard = [
            [
                InlineKeyboardButton("➕ Aggiungi condizione", callback_data="health:add_condition"),
                InlineKeyboardButton("🍽️ Restrizioni alimentari", callback_data="health:dietary")
            ],
            [
                InlineKeyboardButton("💊 Integratori", callback_data="health:supplements"),
                InlineKeyboardButton("📋 Referti medici", callback_data="health:reports")
            ],
            [
                InlineKeyboardButton("🔍 Riepilogo sanitario", callback_data="health:summary"),
                InlineKeyboardButton("🔄 Aggiorna dati", callback_data="health:update")
            ],
            [
                InlineKeyboardButton("🔙 Menu principale", callback_data="menu:back")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = (
            "❤️ *Menu Monitoraggio Sanitario*\n\n"
            "Tieni traccia delle tue condizioni mediche, restrizioni alimentari, "
            "integratori e referti per ricevere consigli personalizzati."
        )
        
        if edit and update.callback_query and update.callback_query.message:
            await update.callback_query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
    
    # Gestisce i callback dei piani alimentari
    async def handle_meal_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
        """
        Gestisce i callback dei piani alimentari.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            action: Azione da eseguire
        """
        user_id = update.effective_user.id
        user_data = self.get_user_data(user_id)
        
        if action == "create":
            # Inizia il processo di creazione di un piano alimentare
            user_data.temp_meal_plan = {}
            user_data.current_context = WAITING_FOR_MEAL_PLAN_NAME
            
            await update.callback_query.edit_message_text(
                "➕ *Crea Piano Alimentare*\n\n"
                "Inserisci un nome per il piano alimentare:",
                parse_mode=ParseMode.MARKDOWN
            )
            
        elif action == "view_plans":
            # Visualizza tutti i piani alimentari
            meal_plans = self.data_manager.get_meal_plans(user_id)
            
            if not meal_plans:
                # Nessun piano trovato
                keyboard = [
                    [
                        InlineKeyboardButton("➕ Crea piano", callback_data="meal:create"),
                        InlineKeyboardButton("🔙 Menu piani", callback_data="menu:meal_plans")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    "🍽️ *Piani Alimentari*\n\n"
                    "Non hai ancora creato piani alimentari. Crea il tuo primo piano!",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                
            else:
                # Mostra la lista dei piani
                text = "🍽️ *I Tuoi Piani Alimentari*\n\n"
                
                for plan in meal_plans:
                    # Formatta le date
                    start_date = datetime.datetime.strptime(plan['start_date'], DATE_FORMAT).strftime(DISPLAY_DATE_FORMAT)
                    end_date = datetime.datetime.strptime(plan['end_date'], DATE_FORMAT).strftime(DISPLAY_DATE_FORMAT)
                    
                    text += f"📋 *{plan['name']}*\n"
                    text += f"📅 Dal {start_date} al {end_date}\n\n"
                
                # Crea la tastiera con i piani
                keyboard = []
                
                for plan in meal_plans[:5]:  # Mostra solo i primi 5 piani
                    keyboard.append([
                        InlineKeyboardButton(plan['name'], callback_data=f"meal:view_plan:{plan['id']}")
                    ])
                
                # Aggiungi pulsanti di navigazione
                keyboard.append([
                    InlineKeyboardButton("➕ Crea piano", callback_data="meal:create"),
                    InlineKeyboardButton("🔙 Menu piani", callback_data="menu:meal_plans")
                ])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
                )
                
        elif action == "today":
            # Visualizza i pasti pianificati per oggi
            today = datetime.date.today().strftime(DATE_FORMAT)
            meals = self.data_manager.get_meals_for_date(user_id, today)
            
            if not meals:
                # Nessun pasto pianificato
                keyboard = [
                    [
                        InlineKeyboardButton("➕ Aggiungi pasto", callback_data="meal:add_today"),
                        InlineKeyboardButton("🔙 Menu piani", callback_data="menu:meal_plans")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    "🍽️ *Pasti di Oggi*\n\n"
                    "Non hai pasti pianificati per oggi. Vuoi aggiungerne uno?",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                
            else:
                # Mostra i pasti di oggi
                today_display = datetime.date.today().strftime(DISPLAY_DATE_FORMAT)
                
                text = f"🍽️ *Pasti di Oggi ({today_display})*\n\n"
                
                # Organizza i pasti per tipo
                meal_types = {
                    "colazione": "🌅 *Colazione*",
                    "pranzo": "☀️ *Pranzo*",
                    "cena": "🌙 *Cena*",
                    "spuntino": "🍎 *Spuntino*"
                }
                
                for meal_type, title in meal_types.items():
                    type_meals = [m for m in meals if m['meal_type'].lower() == meal_type]
                    
                    if type_meals:
                        text += f"{title}\n"
                        
                        for meal in type_meals:
                            text += f"- {meal['description']}\n"
                            
                            # Aggiungi informazioni nutrizionali se presenti
                            if meal['nutrition_info']:
                                try:
                                    nutrition = json.loads(meal['nutrition_info'])
                                    text += f"  📊 {nutrition.get('calories', '?')} kcal, "
                                    text += f"🥩 {nutrition.get('protein', '?')}g, "
                                    text += f"🍞 {nutrition.get('carbs', '?')}g, "
                                    text += f"🧈 {nutrition.get('fat', '?')}g\n"
                                except json.JSONDecodeError:
                                    pass
                        
                        text += "\n"
                
                # Crea la tastiera
                keyboard = [
                    [
                        InlineKeyboardButton("➕ Aggiungi pasto", callback_data="meal:add_today"),
                        InlineKeyboardButton("📆 Cambia data", callback_data="meal:select_date")
                    ],
                    [
                        InlineKeyboardButton("🔙 Menu piani", callback_data="menu:meal_plans")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
                )
    
    # Gestisce i callback delle liste della spesa
    async def handle_shopping_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
        """
        Gestisce i callback delle liste della spesa.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            action: Azione da eseguire
        """
        user_id = update.effective_user.id
        user_data = self.get_user_data(user_id)
        
        if action == "create":
            # Inizia il processo di creazione di una lista della spesa
            user_data.temp_shopping_list = {}
            user_data.current_context = WAITING_FOR_SHOPPING_LIST_NAME
            
            await update.callback_query.edit_message_text(
                "➕ *Crea Lista della Spesa*\n\n"
                "Inserisci un nome per la lista della spesa:",
                parse_mode=ParseMode.MARKDOWN
            )
            
        elif action == "view_all":
            # Visualizza tutte le liste della spesa
            shopping_lists = self.data_manager.get_shopping_lists(user_id)
            
            if not shopping_lists:
                # Nessuna lista trovata
                keyboard = [
                    [
                        InlineKeyboardButton("➕ Crea lista", callback_data="shop:create"),
                        InlineKeyboardButton("🔙 Menu liste", callback_data="menu:shopping")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    "🛒 *Liste della Spesa*\n\n"
                    "Non hai ancora creato liste della spesa. Crea la tua prima lista!",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                
            else:
                # Mostra la lista delle liste della spesa
                text = "🛒 *Le Tue Liste della Spesa*\n\n"
                
                for shopping_list in shopping_lists:
                    created_at = datetime.datetime.strptime(
                        shopping_list['created_at'].split('.')[0],  # Rimuovi i millisecondi
                        "%Y-%m-%d %H:%M:%S"
                    ).strftime("%d/%m/%Y")
                    
                    text += f"📋 *{shopping_list['name']}*\n"
                    text += f"📅 Creata il {created_at}\n\n"
                
                # Crea la tastiera con le liste
                keyboard = []
                
                for shopping_list in shopping_lists:
                    keyboard.append([
                        InlineKeyboardButton(shopping_list['name'], callback_data=f"shop:view_list:{shopping_list['id']}")
                    ])
                
                # Aggiungi pulsanti di navigazione
                keyboard.append([
                    InlineKeyboardButton("➕ Crea lista", callback_data="shop:create"),
                    InlineKeyboardButton("🔙 Menu liste", callback_data="menu:shopping")
                ])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
                )
                
        elif action.startswith("view_list:"):
            # Visualizza gli elementi di una lista della spesa
            list_id = int(action[10:])
            await self.show_shopping_list_items(update, context, list_id)
            
        elif action == "generate":
            # Genera una lista della spesa dall'inventario
            # Chiedi conferma prima di generare
            keyboard = [
                [
                    InlineKeyboardButton("✅ Sì, genera", callback_data="shop:generate_confirm"),
                    InlineKeyboardButton("❌ No, annulla", callback_data="menu:shopping")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                "🔄 *Genera Lista della Spesa*\n\n"
                "Vuoi generare una lista della spesa in base agli alimenti in esaurimento nel tuo inventario?",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
        elif action == "generate_confirm":
            # Genera effettivamente la lista della spesa
            list_id = self.data_manager.generate_shopping_list_from_inventory(user_id)
            
            if list_id:
                # Mostra la lista generata
                await self.show_shopping_list_items(update, context, list_id)
            else:
                # Errore nella generazione
                keyboard = [
                    [
                        InlineKeyboardButton("↩️ Riprova", callback_data="shop:generate"),
                        InlineKeyboardButton("🔙 Menu liste", callback_data="menu:shopping")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    "❌ Si è verificato un errore durante la generazione della lista della spesa. Riprova più tardi.",
                    reply_markup=reply_markup
                )
                
        elif action.startswith("add_item:"):
            # Inizia il processo di aggiunta di un articolo alla lista
            list_id = int(action[9:])
            user_data.temp_shopping_item = {"list_id": list_id}
            user_data.current_context = WAITING_FOR_SHOPPING_ITEM_NAME
            
            await update.callback_query.edit_message_text(
                "➕ *Aggiungi Articolo*\n\n"
                "Inserisci il nome dell'articolo:",
                parse_mode=ParseMode.MARKDOWN
            )
            
        elif action.startswith("complete_all:"):
            # Marca tutti gli elementi della lista come completati
            list_id = int(action[12:])
            
            # Ottieni tutti gli elementi non completati
            items = self.data_manager.get_shopping_list_items(list_id, include_completed=False)
            
            success = True
            for item in items:
                if not self.data_manager.mark_shopping_item_as_completed(item['id'], completed=True):
                    success = False
            
            if success:
                # Aggiorna la vista della lista
                await self.show_shopping_list_items(update, context, list_id)
            else:
                await update.callback_query.edit_message_text(
                    "❌ Si è verificato un errore durante l'aggiornamento degli elementi. Riprova più tardi.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Menu liste", callback_data="menu:shopping")
                    ]])
                )
    
    # Gestisce i callback del monitoraggio sanitario
    async def handle_health_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
        """
        Gestisce i callback del monitoraggio sanitario.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            action: Azione da eseguire
        """
        user_id = update.effective_user.id
        user_data = self.get_user_data(user_id)
        
        if action == "add_condition":
            # Inizia il processo di aggiunta di una condizione medica
            user_data.temp_health_condition = {}
            user_data.current_context = WAITING_FOR_HEALTH_CONDITION_NAME
            
            await update.callback_query.edit_message_text(
                "➕ *Aggiungi Condizione Medica*\n\n"
                "Inserisci il nome della condizione:",
                parse_mode=ParseMode.MARKDOWN
            )
            
        elif action == "dietary":
            # Mostra le restrizioni alimentari
            restrictions = self.data_manager.get_dietary_restrictions(user_id)
            
            text = "🍽️ *Restrizioni Alimentari*\n\n"
            
            if not restrictions:
                text += "Non hai ancora registrato restrizioni alimentari."
            else:
                for restriction in restrictions:
                    severity = ""
                    if restriction['severity']:
                        if restriction['severity'] == "alta":
                            severity = "⚠️ Alta gravità"
                        elif restriction['severity'] == "media":
                            severity = "⚠️ Media gravità"
                        else:
                            severity = "ℹ️ Bassa gravità"
                    
                    text += f"*{restriction['name']}*\n"
                    text += f"🍲 Alimento: {restriction['food_type']}\n"
                    
                    if restriction['reason']:
                        text += f"📝 Motivo: {restriction['reason']}\n"
                    
                    if severity:
                        text += f"{severity}\n"
                    
                    text += "\n"
            
            # Crea la tastiera
            keyboard = [
                [
                    InlineKeyboardButton("➕ Aggiungi restrizione", callback_data="health:add_restriction"),
                    InlineKeyboardButton("🔙 Menu salute", callback_data="menu:health")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
            
        elif action == "supplements":
            # Mostra gli integratori
            supplements = self.data_manager.get_supplements(user_id)
            
            text = "💊 *Integratori*\n\n"
            
            if not supplements:
                text += "Non hai ancora registrato integratori."
            else:
                for supplement in supplements:
                    text += f"*{supplement['name']}*\n"
                    text += f"💊 Dosaggio: {supplement['dosage']}\n"
                    text += f"⏱️ Frequenza: {supplement['frequency']}\n"
                    
                    if supplement['purpose']:
                        text += f"📝 Scopo: {supplement['purpose']}\n"
                    
                    if supplement['start_date']:
                        start_date = datetime.datetime.strptime(supplement['start_date'], DATE_FORMAT).strftime(DISPLAY_DATE_FORMAT)
                        text += f"📅 Inizio: {start_date}\n"
                    
                    if supplement['end_date']:
                        end_date = datetime.datetime.strptime(supplement['end_date'], DATE_FORMAT).strftime(DISPLAY_DATE_FORMAT)
                        text += f"📅 Fine: {end_date}\n"
                    
                    text += "\n"
            
            # Crea la tastiera
            keyboard = [
                [
                    InlineKeyboardButton("➕ Aggiungi integratore", callback_data="health:add_supplement"),
                    InlineKeyboardButton("🔙 Menu salute", callback_data="menu:health")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
            
        elif action == "reports":
            # Mostra i referti medici
            reports = self.data_manager.get_health_reports(user_id)
            
            text = "📋 *Referti Medici*\n\n"
            
            if not reports:
                text += "Non hai ancora registrato referti medici."
            else:
                # Ordina per data, più recenti prima
                reports.sort(key=lambda x: x['date'], reverse=True)
                
                for report in reports:
                    date = datetime.datetime.strptime(report['date'], DATE_FORMAT).strftime(DISPLAY_DATE_FORMAT)
                    
                    text += f"*{report['report_type']}* ({date})\n"
                    text += f"📝 {report['summary']}\n\n"
            
            # Crea la tastiera
            keyboard = [
                [
                    InlineKeyboardButton("➕ Aggiungi referto", callback_data="health:add_report"),
                    InlineKeyboardButton("🔙 Menu salute", callback_data="menu:health")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
            
        elif action == "summary":
            # Mostra un riepilogo sanitario
            conditions = self.data_manager.get_health_conditions(user_id)
            restrictions = self.data_manager.get_dietary_restrictions(user_id)
            supplements = self.data_manager.get_supplements(user_id)
            
            text = "❤️ *Riepilogo Sanitario*\n\n"
            
            # Condizioni mediche
            text += "*Condizioni Mediche:*\n"
            if not conditions:
                text += "Nessuna condizione registrata.\n"
            else:
                for condition in conditions:
                    text += f"- {condition['name']}"
                    if condition['severity']:
                        text += f" ({condition['severity']})"
                    text += "\n"
            
            text += "\n*Restrizioni Alimentari:*\n"
            if not restrictions:
                text += "Nessuna restrizione registrata.\n"
            else:
                for restriction in restrictions:
                    text += f"- {restriction['name']} ({restriction['food_type']})\n"
            
            text += "\n*Integratori Attivi:*\n"
            active_supplements = [s for s in supplements if not s['end_date'] or datetime.datetime.strptime(s['end_date'], DATE_FORMAT).date() >= datetime.date.today()]
            
            if not active_supplements:
                text += "Nessun integratore attivo.\n"
            else:
                for supplement in active_supplements:
                    text += f"- {supplement['name']} ({supplement['dosage']}, {supplement['frequency']})\n"
            
            # Crea la tastiera
            keyboard = [
                [
                    InlineKeyboardButton("📋 Dettagli completi", callback_data="health:detail"),
                    InlineKeyboardButton("🔙 Menu salute", callback_data="menu:health")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
    
    # Gestisce i callback delle impostazioni
    async def handle_setting_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
        """
        Gestisce i callback delle impostazioni.
        
        Args:
            update: Oggetto update di Telegram
            context: Contesto della conversazione
            action: Azione da eseguire
        """
        user_id = update.effective_user.id
        
        if action.startswith("notifications:"):
            # Attiva/disattiva le notifiche
            enabled = action[14:] == "true"
            
            # Salva la preferenza nel database
            self.data_manager.set_user_preference(user_id, "notifications_enabled", str(enabled).lower())
            
            # Aggiorna la vista delle impostazioni
            await self.command_settings(Update(update_id=0, callback_query=update.callback_query), context)
            
        elif action == "expiry_days":
            # Mostra opzioni per i giorni di notifica scadenza
            current_days = int(self.data_manager.get_user_preference(user_id, "expiry_notification_days", "3"))
            
            # Crea la tastiera con le opzioni
            keyboard = []
            
            for days in [1, 3, 5, 7]:
                keyboard.append([
                    InlineKeyboardButton(
                        f"{days} {'giorno' if days == 1 else 'giorni'}{' ✓' if days == current_days else ''}",
                        callback_data=f"setting:set_expiry_days:{days}"
                    )
                ])
            
            keyboard.append([
                InlineKeyboardButton("🔙 Torna alle impostazioni", callback_data="menu:settings")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                "⏰ *Giorni Notifica Scadenza*\n\n"
                "Seleziona quanti giorni prima della scadenza vuoi ricevere le notifiche:",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
        elif action.startswith("set_expiry_days:"):
            # Imposta i giorni di notifica scadenza
            days = int(action[15:])
            
            # Salva la preferenza nel database
            self.data_manager.set_user_preference(user_id, "expiry_notification_days", str(days))
            
            # Aggiorna la vista delle impostazioni
            await self.command_settings(Update(update_id=0, callback_query=update.callback_query), context)
            
        elif action == "language":
            # Mostra opzioni per la lingua
            current_language = self.data_manager.get_user_preference(user_id, "language", "it")
            
            # Crea la tastiera con le opzioni
            keyboard = [
                [
                    InlineKeyboardButton(f"🇮🇹 Italiano{' ✓' if current_language == 'it' else ''}", callback_data="setting:set_language:it"),
                    InlineKeyboardButton(f"🇬🇧 English{' ✓' if current_language == 'en' else ''}", callback_data="setting:set_language:en")
                ],
                [
                    InlineKeyboardButton("🔙 Torna alle impostazioni", callback_data="menu:settings")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                "🌐 *Lingua*\n\n"
                "Seleziona la lingua preferita:",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
        elif action.startswith("set_language:"):
            # Imposta la lingua
            language = action[13:]
            
            # Salva la preferenza nel database
            self.data_manager.set_user_preference(user_id, "language", language)
            
            # Aggiorna la vista delle impostazioni
            await self.command_settings(Update(update_id=0, callback_query=update.callback_query), context)
            
        elif action == "export_data":
            # Esporta i dati dell'utente
            export_data = self.data_manager.export_user_data(user_id)
            
            if export_data:
                # Converti in JSON
                json_data = json.dumps(export_data, indent=2, ensure_ascii=False)
                
                # Crea un file temporaneo
                with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as temp_file:
                    temp_file.write(json_data.encode('utf-8'))
                    temp_file_path = temp_file.name
                
                # Invia il file
                await update.callback_query.message.reply_document(
                    document=open(temp_file_path, 'rb'),
                    filename=f"export_data_{datetime.date.today().strftime('%Y%m%d')}.json",
                    caption="📤 Ecco l'esportazione dei tuoi dati. Puoi importarli in seguito o su un altro dispositivo."
                )
                
                # Elimina il file temporaneo
                os.unlink(temp_file_path)
                
                # Aggiorna il messaggio
                await update.callback_query.edit_message_text(
                    "✅ Dati esportati con successo. Controlla i messaggi per il file.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Torna alle impostazioni", callback_data="menu:settings")
                    ]])
                )
                
            else:
                await update.callback_query.edit_message_text(
                    "❌ Si è verificato un errore durante l'esportazione dei dati. Riprova più tardi.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Torna alle impostazioni", callback_data="menu:settings")
                    ]])
                )
                
        elif action == "import_data":
            # Mostra istruzioni per l'importazione
            await update.callback_query.edit_message_text(
                "📥 *Importa Dati*\n\n"
                "Per importare i tuoi dati, invia un file JSON generato precedentemente con l'esportazione.\n\n"
                "⚠️ *Attenzione*: L'importazione sovrascriverà i dati esistenti. "
                "Assicurati di esportare i dati attuali prima di procedere se necessario.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Torna alle impostazioni", callback_data="menu:settings")
                ]]),
                parse_mode=ParseMode.MARKDOWN
            )

if __name__ == "__main__":
    """Test di base del modulo."""
    import os
    from dotenv import load_dotenv
    from anthropic_helper import AnthropicHelper
    
    # Carica variabili d'ambiente
    load_dotenv()
    
    # Verifica le variabili d'ambiente necessarie
    required_vars = ['TELEGRAM_BOT_TOKEN', 'ANTHROPIC_API_KEY']
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        print(f"⚠️ Variabili d'ambiente mancanti: {', '.join(missing_vars)}")
        print("Imposta queste variabili nel file .env prima di continuare.")
        exit(1)
    
    print("🤖 Avvio dell'assistente personale Claude...")
    
    # Configurazione
    config = {
        'token': os.environ['TELEGRAM_BOT_TOKEN'],
        'admin_user_ids': os.environ.get('ADMIN_USER_IDS', ''),
        'allowed_user_ids': os.environ.get('ALLOWED_USER_IDS', '*'),
        'stream': True
    }
    
    # Inizializza l'helper di Anthropic
    anthropic = AnthropicHelper(api_key=os.environ['ANTHROPIC_API_KEY'])
    
    # Inizializza e avvia il bot
    bot = ChatGPTTelegramBot(config=config, openai=anthropic)
    bot.run()
