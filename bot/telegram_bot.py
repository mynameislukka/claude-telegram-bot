                    "⚠️ La data deve essere compresa nel periodo del piano alimentare "
                    f"({start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}).\n"
                    "Per favore, inserisci una data valida:"
                )
                return ADD_MEAL_DATE
            
            # Converti in formato SQL (YYYY-MM-DD)
            context.user_data["meal_date"] = date_obj.strftime("%Y-%m-%d")
            
            # Procedi con il tipo di pasto
            await update.message.reply_text(
                f"👍 Data: {date_obj.strftime('%d/%m/%Y')}\n\n"
                f"Ora seleziona il tipo di pasto:\n"
                f"(es. colazione, pranzo, cena, spuntino)\n"
                f"(oppure invia /cancel per annullare)"
            )
            
            return ADD_MEAL_TYPE
        
        except (ValueError, IndexError):
            await update.message.reply_text(
                "❌ Formato data non valido.\n"
                "Per favore, inserisci la data nel formato GG/MM/AAAA:"
            )
            return ADD_MEAL_DATE
    
    async def add_meal_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce l'input del tipo di pasto."""
        context.user_data["meal_type"] = update.message.text
        
        await update.message.reply_text(
            f"👍 Tipo: {update.message.text}\n\n"
            f"Ora inserisci una descrizione del pasto:\n"
            f"(oppure invia /cancel per annullare)"
        )
        
        return ADD_MEAL_DESCRIPTION
    
    async def add_meal_description(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce l'input della descrizione del pasto."""
        context.user_data["meal_description"] = update.message.text
        
        await update.message.reply_text(
            f"👍 Descrizione registrata.\n\n"
            f"Per finire, aggiungi la ricetta o dettagli nutrizionali (opzionale):\n"
            f"(oppure scrivi 'nessuna' per saltare)\n"
            f"(oppure invia /cancel per annullare)"
        )
        
        return ADD_MEAL_RECIPE
    
    async def add_meal_recipe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce l'input della ricetta e completa l'aggiunta del pasto."""
        text = update.message.text
        
        if text.lower() in ["nessuna", "no", "n/a", "-"]:
            context.user_data["meal_recipe"] = None
        else:
            context.user_data["meal_recipe"] = text
        
        # Recupera i dati del pasto
        plan_id = context.user_data["meal_plan_id"]
        date = context.user_data["meal_date"]
        meal_type = context.user_data["meal_type"]
        description = context.user_data["meal_description"]
        recipe = context.user_data.get("meal_recipe")
        
        # Aggiungi il pasto al piano
        meal_id = await self.data_manager.add_meal_to_plan(
            plan_id=plan_id,
            date=date,
            meal_type=meal_type,
            description=description,
            recipe=recipe
        )
        
        if meal_id:
            # Formatta la data per la visualizzazione
            date_obj = datetime.datetime.strptime(date, "%Y-%m-%d").date()
            
            # Formatta le informazioni per la visualizzazione
            recipe_text = f"\n📝 Ricetta: {recipe}" if recipe else ""
            
            await update.message.reply_text(
                f"✅ *Pasto aggiunto al piano alimentare!*\n\n"
                f"📅 {date_obj.strftime('%d/%m/%Y')}\n"
                f"🍽️ {meal_type}\n"
                f"🍳 {description}"
                f"{recipe_text}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_keyboard_markup(Menu.MEAL_PLAN)
            )
        else:
            await update.message.reply_text(
                "❌ Si è verificato un errore durante l'aggiunta del pasto.\n"
                "Riprova più tardi.",
                reply_markup=get_keyboard_markup(Menu.MEAL_PLAN)
            )
        
        # Pulisci i dati dell'utente
        user_id = update.effective_user.id
        self._clear_user_data(user_id)
        
        return MEAL_PLAN_MENU
    
    async def show_current_meal_plans(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostra i piani alimentari attualmente attivi."""
        user_id = update.effective_user.id
        
        # Ottieni i piani attivi
        plans = await self.data_manager.get_meal_plans(user_id, current_only=True)
        
        if not plans:
            await update.message.reply_text(
                "🔍 Non hai piani alimentari attivi.\n\n"
                "Puoi creare un nuovo piano usando '➕ Nuovo Piano'.",
                reply_markup=get_keyboard_markup(Menu.MEAL_PLAN)
            )
            return MEAL_PLAN_MENU
        
        # Crea il messaggio con la lista dei piani
        message = "🍽️ *I tuoi piani alimentari attivi:*\n\n"
        
        for plan in plans:
            # Formatta le date
            start_obj = datetime.datetime.strptime(plan["start_date"], "%Y-%m-%d").date()
            end_obj = datetime.datetime.strptime(plan["end_date"], "%Y-%m-%d").date()
            
            # Calcola i giorni rimanenti
            days_left = (end_obj - datetime.date.today()).days
            days_text = f"{days_left} giorni rimanenti" if days_left > 0 else "Ultimo giorno"
            
            message += (
                f"*{plan['name']}*\n"
                f"📅 {start_obj.strftime('%d/%m/%Y')} - {end_obj.strftime('%d/%m/%Y')}\n"
                f"⏱️ {days_text}\n\n"
            )
        
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Pulsanti per selezionare un piano
        buttons = []
        for plan in plans:
            buttons.append([(plan["name"], f"select_plan:{plan['id']}")])
        
        await update.message.reply_text(
            "Seleziona un piano per visualizzare i dettagli:",
            reply_markup=get_inline_keyboard(buttons)
        )
        
        return MEAL_PLAN_MENU
    
    async def show_today_meals(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostra i pasti pianificati per oggi."""
        user_id = update.effective_user.id
        today = datetime.date.today().strftime("%Y-%m-%d")
        
        # Ottieni i pasti di oggi
        meals = await self.data_manager.get_meals_for_date(user_id, today)
        
        if not meals:
            await update.message.reply_text(
                "🍽️ Non hai pasti pianificati per oggi.\n\n"
                "Puoi aggiungere un pasto usando '🍳 Aggiungi Pasto'.",
                reply_markup=get_keyboard_markup(Menu.MEAL_PLAN)
            )
            return MEAL_PLAN_MENU
        
        # Crea il messaggio con i pasti di oggi
        message = f"🍽️ *I tuoi pasti per oggi ({datetime.date.today().strftime('%d/%m/%Y')}):*\n\n"
        
        # Ordina i pasti per tipo (colazione, pranzo, cena)
        meal_order = {"colazione": 1, "pranzo": 2, "cena": 3}
        
        sorted_meals = sorted(
            meals,
            key=lambda x: meal_order.get(x["meal_type"].lower(), 99)
        )
        
        for meal in sorted_meals:
            # Ottieni il nome del piano
            plan = await self.data_manager.get_meal_plan(meal["plan_id"])
            plan_name = plan["name"] if plan else "Piano sconosciuto"
            
            message += (
                f"*{meal['meal_type']}*\n"
                f"🍳 {meal['description']}\n"
                f"📝 Piano: {plan_name}\n\n"
            )
        
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_keyboard_markup(Menu.MEAL_PLAN)
        )
        
        return MEAL_PLAN_MENU
    
    async def search_recipes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Avvia la ricerca di ricette."""
        await update.message.reply_text(
            "🔍 *Cerca Ricette*\n\n"
            "Inserisci cosa stai cercando, ad esempio:\n"
            "- Un ingrediente (es. 'zucchine')\n"
            "- Un tipo di piatto (es. 'pasta')\n"
            "- Una dieta specifica (es. 'vegano')\n"
            "- Una combinazione (es. 'pasta vegetariana')",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Imposta il contesto di ricerca
        user_id = update.effective_user.id
        self.active_contexts[user_id] = "search_recipes"
        
        return MEAL_PLAN_MENU
    
    async def show_nutrition_analysis(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostra un'analisi nutrizionale dei pasti pianificati."""
        user_id = update.effective_user.id
        
        # Verificare se c'è un piano attivo
        if user_id in self.current_plans:
            plan_id = self.current_plans[user_id]
            plan = await self.data_manager.get_meal_plan(plan_id)
            
            if plan:
                # Ottieni tutti i pasti del piano
                with self.show_typing(update):
                    meals = await self.data_manager.get_meals_for_plan(plan_id)
                    
                    if not meals:
                        await update.message.reply_text(
                            f"⚠️ Il piano '{plan['name']}' non ha ancora pasti.\n\n"
                            f"Aggiungi prima alcuni pasti per vedere l'analisi nutrizionale.",
                            reply_markup=get_keyboard_markup(Menu.MEAL_PLAN)
                        )
                        return MEAL_PLAN_MENU
                    
                    # Usa Claude per generare un'analisi nutrizionale
                    meals_text = "\n".join([
                        f"- {m['meal_type']} ({m['date']}): {m['description']}"
                        for m in meals
                    ])
                    
                    # Ottieni le restrizioni alimentari dell'utente
                    restrictions = await self.data_manager.get_dietary_restrictions(user_id)
                    restrictions_text = ""
                    if restrictions:
                        restrictions_text = "\n\nRestrizioni alimentari dell'utente:\n" + "\n".join([
                            f"- {r['name']} ({r['food_type']})"
                            for r in restrictions
                        ])
                    
                    prompt = (
                        f"Analizza nutrizionalmente i seguenti pasti del piano alimentare '{plan['name']}':\n\n"
                        f"{meals_text}\n{restrictions_text}\n\n"
                        f"Fornisci un'analisi che includa:\n"
                        f"1. Stima delle calorie e dei macronutrienti (proteine, carboidrati, grassi)\n"
                        f"2. Valutazione dell'equilibrio nutrizionale\n"
                        f"3. Punti di forza e possibili carenze\n"
                        f"4. Suggerimenti per migliorare il piano, rispettando eventuali restrizioni\n\n"
                        f"Mantieni l'analisi concisa e pratica."
                    )
                    
                    response = await self.claude_helper.simple_query(prompt)
                    
                    await update.message.reply_text(
                        f"📊 *Analisi Nutrizionale: {plan['name']}*\n\n{response}",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=get_keyboard_markup(Menu.MEAL_PLAN)
                    )
                    
                    return MEAL_PLAN_MENU
        
        # Se non c'è un piano attivo, mostra l'elenco dei piani disponibili
        plans = await self.data_manager.get_meal_plans(user_id)
        
        if not plans:
            # Nessun piano disponibile
            await update.message.reply_text(
                "❌ Non hai piani alimentari.\n\n"
                "Crea prima un nuovo piano usando '➕ Nuovo Piano'.",
                reply_markup=get_keyboard_markup(Menu.MEAL_PLAN)
            )
            return MEAL_PLAN_MENU
        
        # Crea i pulsanti per la selezione del piano
        buttons = []
        for plan in plans:
            buttons.append([(plan["name"], f"select_plan_analysis:{plan['id']}")])
        
        await update.message.reply_text(
            "🍽️ *Seleziona un piano alimentare:*\n\n"
            "Di quale piano vuoi vedere l'analisi nutrizionale?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_inline_keyboard(buttons)
        )
        
        # Imposta il contesto
        self.active_contexts[user_id] = "select_plan_for_analysis"
        
        return MEAL_PLAN_MENU
    
    # Funzioni per le liste della spesa
    
    async def start_add_shopping_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Avvia il processo di creazione di una nuova lista della spesa."""
        await update.message.reply_text(
            "🛒 *Crea Nuova Lista della Spesa*\n\n"
            "Inserisci un nome per la tua nuova lista:\n"
            "(oppure invia /cancel per annullare)",
            parse_mode=ParseMode.MARKDOWN
        )
        
        return ADD_SHOPPING_LIST_NAME
    
    async def add_shopping_list_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce l'input del nome della lista della spesa e la crea."""
        user_id = update.effective_user.id
        list_name = update.message.text
        
        # Crea la lista della spesa
        list_id = await self.data_manager.create_shopping_list(
            user_id=user_id,
            name=list_name
        )
        
        if list_id:
            # Imposta la lista corrente
            self.current_lists[user_id] = list_id
            
            await update.message.reply_text(
                f"✅ *Lista della spesa creata!*\n\n"
                f"🛒 {list_name}\n\n"
                f"Ora puoi aggiungere articoli a questa lista usando '🛍️ Aggiungi Articolo'.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_keyboard_markup(Menu.SHOPPING_LIST)
            )
        else:
            await update.message.reply_text(
                "❌ Si è verificato un errore durante la creazione della lista della spesa.\n"
                "Riprova più tardi.",
                reply_markup=get_keyboard_markup(Menu.SHOPPING_LIST)
            )
        
        return SHOPPING_LIST_MENU
    
    async def start_add_shopping_item(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Avvia il processo di aggiunta di un articolo alla lista della spesa."""
        user_id = update.effective_user.id
        
        # Verifica se c'è una lista attiva
        if user_id in self.current_lists:
            list_id = self.current_lists[user_id]
            context.user_data["shopping_list_id"] = list_id
            
            # Ottieni i dettagli della lista
            shopping_list = await self.data_manager.get_shopping_list(list_id)
            
            if shopping_list:
                await update.message.reply_text(
                    f"🛍️ *Aggiungi Articolo a {shopping_list['name']}*\n\n"
                    f"Inserisci il nome dell'articolo da aggiungere:\n"
                    f"(oppure invia /cancel per annullare)",
                    parse_mode=ParseMode.MARKDOWN
                )
                
                return ADD_SHOPPING_ITEM_NAME
        
        # Se non c'è una lista attiva, mostra l'elenco delle liste disponibili
        shopping_lists = await self.data_manager.get_shopping_lists(user_id)
        
        if not shopping_lists:
            # Nessuna lista disponibile
            await update.message.reply_text(
                "❌ Non hai liste della spesa.\n\n"
                "Crea prima una nuova lista usando '➕ Nuova Lista'.",
                reply_markup=get_keyboard_markup(Menu.SHOPPING_LIST)
            )
            return SHOPPING_LIST_MENU
        
        # Crea i pulsanti per la selezione della lista
        buttons = []
        for lst in shopping_lists:
            buttons.append([(lst["name"], f"select_list:{lst['id']}")])
        
        await update.message.reply_text(
            "🛒 *Seleziona una lista della spesa:*\n\n"
            "A quale lista vuoi aggiungere un articolo?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_inline_keyboard(buttons)
        )
        
        # Imposta il contesto
        self.active_contexts[user_id] = "select_list_for_item"
        
        return SHOPPING_LIST_MENU
    
    async def add_shopping_item_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce l'input del nome dell'articolo."""
        context.user_data["shopping_item_name"] = update.message.text
        
        await update.message.reply_text(
            f"👍 Articolo: {update.message.text}\n\n"
            f"Ora inserisci la quantità (opzionale):\n"
            f"(scrivi 'nessuna' per saltare)\n"
            f"(oppure invia /cancel per annullare)"
        )
        
        return ADD_SHOPPING_ITEM_QUANTITY
    
    async def add_shopping_item_quantity(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce l'input della quantità dell'articolo."""
        text = update.message.text
        
        if text.lower() in ["nessuna", "no", "n/a", "-"]:
            context.user_data["shopping_item_quantity"] = None
        else:
            try:
                quantity = float(text.replace(',', '.'))
                context.user_data["shopping_item_quantity"] = quantity
            except ValueError:
                await update.message.reply_text(
                    "❌ La quantità deve essere un numero.\n"
                    "Per favore, inserisci un valore numerico o scrivi 'nessuna':"
                )
                return ADD_SHOPPING_ITEM_QUANTITY
        
        await update.message.reply_text(
            f"👍 Quantità registrata.\n\n"
            f"Ora inserisci l'unità di misura (opzionale):\n"
            f"(es. g, kg, pz, l, oppure scrivi 'nessuna' per saltare)\n"
            f"(oppure invia /cancel per annullare)"
        )
        
        return ADD_SHOPPING_ITEM_UNIT
    
    async def add_shopping_item_unit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce l'input dell'unità di misura dell'articolo."""
        text = update.message.text
        
        if text.lower() in ["nessuna", "no", "n/a", "-"]:
            context.user_data["shopping_item_unit"] = None
        else:
            context.user_data["shopping_item_unit"] = text
        
        await update.message.reply_text(
            f"👍 Unità registrata.\n\n"
            f"Per finire, seleziona una categoria (opzionale):\n"
            f"(es. Frutta, Verdura, Carne, Latticini, oppure scrivi 'nessuna' per saltare)\n"
            f"(oppure invia /cancel per annullare)"
        )
        
        return ADD_SHOPPING_ITEM_CATEGORY
    
    async def add_shopping_item_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce l'input della categoria e completa l'aggiunta dell'articolo."""
        text = update.message.text
        
        if text.lower() in ["nessuna", "no", "n/a", "-"]:
            context.user_data["shopping_item_category"] = "Generale"
        else:
            context.user_data["shopping_item_category"] = text
        
        # Recupera i dati dell'articolo
        list_id = context.user_data["shopping_list_id"]
        name = context.user_data["shopping_item_name"]
        quantity = context.user_data.get("shopping_item_quantity")
        unit = context.user_data.get("shopping_item_unit")
        category = context.user_data["shopping_item_category"]
        
        # Aggiungi l'articolo alla lista
        item_id = await self.data_manager.add_shopping_item(
            list_id=list_id,
            name=name,
            quantity=quantity,
            unit=unit,
            category=category
        )
        
        if item_id:
            # Formatta le informazioni per la visualizzazione
            quantity_text = f"{quantity} {unit}" if quantity and unit else (
                f"{quantity}" if quantity else ""
            )
            
            quantity_display = f" - {quantity_text}" if quantity_text else ""
            
            await update.message.reply_text(
                f"✅ *Articolo aggiunto alla lista della spesa!*\n\n"
                f"🛒 {name}{quantity_display}\n"
                f"🏷️ Categoria: {category}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_keyboard_markup(Menu.SHOPPING_LIST)
            )
        else:
            await update.message.reply_text(
                "❌ Si è verificato un errore durante l'aggiunta dell'articolo.\n"
                "Riprova più tardi.",
                reply_markup=get_keyboard_markup(Menu.SHOPPING_LIST)
            )
        
        # Pulisci i dati dell'utente
        user_id = update.effective_user.id
        self._clear_user_data(user_id)
        
        return SHOPPING_LIST_MENU
    
    async def show_shopping_lists(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostra le liste della spesa disponibili."""
        user_id = update.effective_user.id
        
        # Ottieni le liste della spesa
        shopping_lists = await self.data_manager.get_shopping_lists(user_id)
        
        if not shopping_lists:
            await update.message.reply_text(
                "🔍 Non hai liste della spesa.\n\n"
                "Puoi creare una nuova lista usando '➕ Nuova Lista'.",
                reply_markup=get_keyboard_markup(Menu.SHOPPING_LIST)
            )
            return SHOPPING_LIST_MENU
        
        # Crea il messaggio con la lista delle liste della spesa
        message = "🛒 *Le tue liste della spesa:*\n\n"
        
        for lst in shopping_lists:
            # Ottieni il conteggio degli articoli nella lista
            items = await self.data_manager.get_shopping_list_items(lst["id"])
            completed = await self.data_manager.get_shopping_list_items(lst["id"], include_completed=True)
            
            # Calcola la percentuale di completamento
            total_items = len(completed)
            completed_items = len([i for i in completed if i["completed"]])
            
            completion_percentage = 0
            if total_items > 0:
                completion_percentage = int((completed_items / total_items) * 100)
            
            # Aggiungi alla lista
            message += (
                f"*{lst['name']}*\n"
                f"📋 {len(items)} articoli da acquistare\n"
                f"✅ Completamento: {completion_percentage}%\n\n"
            )
        
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Pulsanti per selezionare una lista
        buttons = []
        for lst in shopping_lists:
            buttons.append([(lst["name"], f"view_list:{lst['id']}")])
        
        await update.message.reply_text(
            "Seleziona una lista per visualizzare gli articoli:",
            reply_markup=get_inline_keyboard(buttons)
        )
        
        return SHOPPING_LIST_MENU
    
    async def start_shopping_list_from_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Avvia il processo di creazione di una lista della spesa da una foto."""
        await update.message.reply_text(
            "📸 *Lista della Spesa da Foto*\n\n"
            "Invia una foto della tua lista della spesa scritta a mano o stampata.\n"
            "Analizzerò il contenuto e creerò una lista digitale.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Imposta il contesto di acquisizione foto
        user_id = update.effective_user.id
        self.active_contexts[user_id] = "shopping_list_photo"
        
        return SHOPPING_LIST_MENU
    
    async def process_shopping_list_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE, from_document=False):
        """Elabora la foto di una lista della spesa."""
        user_id = update.effective_user.id
        
        # Mostra che stiamo elaborando
        processing_message = await update.message.reply_text(
            "🔍 Sto analizzando la lista della spesa nell'immagine...\n"
            "Questo potrebbe richiedere alcuni secondi."
        )
        
        try:
            # Ottieni la foto
            if from_document:
                photo_data = context.user_data.get("photo_data")
                if not photo_data:
                    await update.message.reply_text(
                        "❌ Errore nel recupero dell'immagine. Riprova."
                    )
                    return SHOPPING_LIST_MENU
            else:
                # Ottieni la foto con la risoluzione più alta
                photo = update.message.photo[-1]
                photo_file = await context.bot.get_file(photo.file_id)
                photo_bytes = await photo_file.download_as_bytearray()
                photo_data = BytesIO(photo_bytes)
            
            # Utilizza Claude Vision per analizzare la lista
            prompt = (
                "Questa è una foto di una lista della spesa scritta a mano o stampata. "
                "Identifica tutti gli articoli elencati e formattali come una lista. "
                "Se vedi quantità o categorie specifiche, includile. "
                "Rispondi solo con l'elenco degli articoli, uno per riga, nel formato: "
                "NOME_ARTICOLO [QUANTITÀ] [UNITÀ] [CATEGORIA]"
            )
            
            # Analizza l'immagine con Claude
            response = await self.claude_helper.analyze_image(
                image_data=photo_data,
                query=prompt,
                image_format="jpeg"
            )
            
            # Elabora la risposta per estrarre gli articoli
            lines = response.strip().split('\n')
            items = []
            
            for line in lines:
                if not line.strip():
                    continue
                
                # Pattern semplice per riconoscere quantità e unità
                # Esempio: "Pomodori 500 g Verdura" -> nome: Pomodori, quantità: 500, unità: g, categoria: Verdura
                parts = line.strip().split()
                
                if len(parts) >= 1:
                    item = {"name": parts[0]}
                    
                    # Se ci sono più parti, prova a interpretare
                    if len(parts) >= 3:
                        try:
                            # Seconda parte potrebbe essere la quantità
                            quantity = float(parts[1].replace(',', '.'))
                            item["quantity"] = quantity
                            
                            # Terza parte potrebbe essere l'unità
                            item["unit"] = parts[2]
                            
                            # Se ci sono altre parti, potrebbero essere la categoria
                            if len(parts) >= 4:
                                item["category"] = " ".join(parts[3:])
                            else:
                                item["category"] = "Generale"
                        except ValueError:
                            # Se non è un numero, tratta tutto come nome
                            item["name"] = " ".join(parts)
                            item["category"] = "Generale"
                    else:
                        # Solo nome
                        item["name"] = " ".join(parts)
                        item["category"] = "Generale"
                    
                    items.append(item)
            
            # Verifica che ci siano articoli riconosciuti
            if not items:
                await processing_message.edit_                "🔍 Sto analizzando l'immagine con Claude. Un attimo di pazienza..."
            )
            
            # Preparazione per l'analisi
            await self.analyze_image_with_claude(update, context, query, "Descrivi dettagliatamente cosa vedi in questa immagine.")
        
        elif command == "analyze_food" and "photo_data" in context.user_data:
            # Usa la foto per analisi di alimenti
            self.active_contexts[user_id] = "food_photo"
            
            await query.edit_message_text(
                "🍎 Sto analizzando l'alimento nell'immagine. Un attimo di pazienza..."
            )
            
            # Preparazione per l'analisi
            prompt = (
                "Questa è un'immagine di cibo o ingredienti. Identifica gli alimenti presenti, "
                "fornisci informazioni nutrizionali approssimative e suggerisci possibili utilizzi "
                "in ricette. Se vedi una data di scadenza, segnalala."
            )
            await self.analyze_image_with_claude(update, context, query, prompt)
        
        elif command == "recognize_list" and "photo_data" in context.user_data:
            # Usa la foto per riconoscere una lista della spesa
            self.active_contexts[user_id] = "shopping_list_photo"
            
            await query.edit_message_text(
                "🛒 Sto analizzando la lista della spesa nell'immagine. Un attimo di pazienza..."
            )
            
            # Preparazione per l'analisi
            prompt = (
                "Questa è un'immagine di una lista della spesa. Estrai tutti gli articoli "
                "che vedi elencati. Formatta la risposta come una lista semplice di elementi, "
                "uno per riga. Se ci sono quantità specificate, includile."
            )
            await self.analyze_image_with_claude(update, context, query, prompt)
        
        # Altri comandi di callback...
        # Puoi aggiungere qui gli altri handler delle callback
        
        # Se il comando non è stato gestito
        else:
            await query.edit_message_text(
                "Comando non riconosciuto o non più disponibile."
            )
    
    # Funzioni per l'interfaccia dei menu principali
    
    async def show_meal_plan_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostra il menu dei piani alimentari."""
        await update.message.reply_text(
            "🍽️ *Menu Piani Alimentari*\n\n"
            "Gestisci i tuoi piani alimentari e pasti:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_keyboard_markup(Menu.MEAL_PLAN)
        )
        
        return MEAL_PLAN_MENU
    
    async def show_inventory_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostra il menu dell'inventario alimentare."""
        await update.message.reply_text(
            "🥑 *Menu Inventario Alimenti*\n\n"
            "Gestisci il tuo inventario di alimenti:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_keyboard_markup(Menu.INVENTORY)
        )
        
        return INVENTORY_MENU
    
    async def show_shopping_list_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostra il menu delle liste della spesa."""
        await update.message.reply_text(
            "🛒 *Menu Lista della Spesa*\n\n"
            "Gestisci le tue liste della spesa:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_keyboard_markup(Menu.SHOPPING_LIST)
        )
        
        return SHOPPING_LIST_MENU
    
    async def show_health_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostra il menu salute."""
        await update.message.reply_text(
            "🏥 *Menu Salute*\n\n"
            "Gestisci le tue informazioni sanitarie:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_keyboard_markup(Menu.HEALTH)
        )
        
        return HEALTH_MENU
    
    # Funzioni per l'inventario alimentare
    
    async def start_add_food(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Avvia il processo di aggiunta di un alimento all'inventario."""
        await update.message.reply_text(
            "🥑 *Aggiungi Alimento all'Inventario*\n\n"
            "Inserisci il nome dell'alimento che vuoi aggiungere:\n"
            "(oppure invia /cancel per annullare)",
            parse_mode=ParseMode.MARKDOWN
        )
        
        return ADD_FOOD_ITEM
    
    async def add_food_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce l'input del nome dell'alimento."""
        context.user_data["food_name"] = update.message.text
        
        await update.message.reply_text(
            f"👍 {update.message.text}\n\n"
            f"Ora inserisci la quantità numerica:\n"
            f"(oppure invia /cancel per annullare)"
        )
        
        return ADD_FOOD_QUANTITY
    
    async def add_food_quantity(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce l'input della quantità dell'alimento."""
        try:
            quantity = float(update.message.text.replace(',', '.'))
            context.user_data["food_quantity"] = quantity
            
            await update.message.reply_text(
                f"👍 Quantità: {quantity}\n\n"
                f"Ora inserisci l'unità di misura (es. g, kg, pz, l):\n"
                f"(oppure invia /cancel per annullare)"
            )
            
            return ADD_FOOD_UNIT
        
        except ValueError:
            await update.message.reply_text(
                "❌ La quantità deve essere un numero.\n"
                "Per favore, inserisci un valore numerico:"
            )
            
            return ADD_FOOD_QUANTITY
    
    async def add_food_unit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce l'input dell'unità di misura dell'alimento."""
        context.user_data["food_unit"] = update.message.text
        
        await update.message.reply_text(
            f"👍 Unità: {update.message.text}\n\n"
            f"Ora inserisci la data di scadenza (formato GG/MM/AAAA):\n"
            f"(oppure scrivi 'nessuna' se non applicabile)\n"
            f"(oppure invia /cancel per annullare)"
        )
        
        return ADD_FOOD_EXPIRY
    
    async def add_food_expiry(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce l'input della data di scadenza."""
        text = update.message.text
        
        if text.lower() in ["nessuna", "no", "n/a", "-"]:
            context.user_data["food_expiry"] = None
        else:
            # Prova a convertire la data
            try:
                # Supporta formati comuni come GG/MM/AAAA o AAAA-MM-GG
                if "/" in text:
                    day, month, year = text.split('/')
                    date_obj = datetime.date(int(year), int(month), int(day))
                elif "-" in text:
                    parts = text.split('-')
                    if len(parts[0]) == 4:  # AAAA-MM-GG
                        year, month, day = parts
                    else:  # GG-MM-AAAA
                        day, month, year = parts
                    date_obj = datetime.date(int(year), int(month), int(day))
                else:
                    raise ValueError("Formato data non riconosciuto")
                
                # Converti in formato SQL (YYYY-MM-DD)
                context.user_data["food_expiry"] = date_obj.strftime("%Y-%m-%d")
            
            except (ValueError, IndexError):
                await update.message.reply_text(
                    "❌ Formato data non valido.\n"
                    "Per favore, inserisci la data nel formato GG/MM/AAAA o scrivi 'nessuna':"
                )
                return ADD_FOOD_EXPIRY
        
        # Procedi con la categoria
        await update.message.reply_text(
            f"👍 Data di scadenza registrata.\n\n"
            f"Ora seleziona una categoria per l'alimento:\n"
            f"(es. Frutta, Verdura, Carne, Pesce, Latticini, etc.)\n"
            f"(oppure invia /cancel per annullare)"
        )
        
        return ADD_FOOD_CATEGORY
    
    async def add_food_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce l'input della categoria dell'alimento."""
        context.user_data["food_category"] = update.message.text
        
        await update.message.reply_text(
            f"👍 Categoria: {update.message.text}\n\n"
            f"Per finire, aggiungi delle note (opzionale):\n"
            f"(oppure scrivi 'nessuna' per saltare)\n"
            f"(oppure invia /cancel per annullare)"
        )
        
        return ADD_FOOD_NOTES
    
    async def add_food_notes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce l'input delle note e completa l'aggiunta dell'alimento."""
        text = update.message.text
        
        if text.lower() in ["nessuna", "no", "n/a", "-"]:
            context.user_data["food_notes"] = None
        else:
            context.user_data["food_notes"] = text
        
        # Recupera i dati dell'alimento
        user_id = update.effective_user.id
        name = context.user_data["food_name"]
        quantity = context.user_data["food_quantity"]
        unit = context.user_data["food_unit"]
        expiry = context.user_data.get("food_expiry")
        category = context.user_data["food_category"]
        notes = context.user_data.get("food_notes")
        
        # Aggiungi l'alimento all'inventario
        item_id = await self.data_manager.add_food_item(
            user_id=user_id,
            name=name,
            category=category,
            quantity=quantity,
            unit=unit,
            expiry_date=expiry,
            notes=notes
        )
        
        if item_id:
            # Formatta le informazioni per la visualizzazione
            expiry_text = f"\n📅 Scadenza: {expiry}" if expiry else ""
            notes_text = f"\n📝 Note: {notes}" if notes else ""
            
            await update.message.reply_text(
                f"✅ *Alimento aggiunto all'inventario!*\n\n"
                f"🥑 {name}\n"
                f"🔢 Quantità: {quantity} {unit}\n"
                f"🏷️ Categoria: {category}"
                f"{expiry_text}"
                f"{notes_text}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_keyboard_markup(Menu.INVENTORY)
            )
        else:
            await update.message.reply_text(
                "❌ Si è verificato un errore durante l'aggiunta dell'alimento.\n"
                "Riprova più tardi.",
                reply_markup=get_keyboard_markup(Menu.INVENTORY)
            )
        
        # Pulisci i dati dell'utente
        self._clear_user_data(user_id)
        
        return INVENTORY_MENU
    
    async def show_inventory(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostra l'inventario alimentare dell'utente."""
        user_id = update.effective_user.id
        
        # Ottieni l'inventario
        inventory = await self.data_manager.get_food_inventory(user_id)
        
        if not inventory:
            await update.message.reply_text(
                "🔍 Il tuo inventario è vuoto.\n\n"
                "Puoi aggiungere alimenti usando il pulsante '➕ Aggiungi Alimento'.",
                reply_markup=get_keyboard_markup(Menu.INVENTORY)
            )
            return INVENTORY_MENU
        
        # Raggruppa per categoria
        categories = {}
        for item in inventory:
            cat = item["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(item)
        
        # Crea il messaggio con la lista dell'inventario
        message = "🥑 *Il tuo inventario alimentare:*\n\n"
        
        for category, items in categories.items():
            message += f"*{category}:*\n"
            for item in items:
                expiry = f" (Scad: {item['expiry_date']})" if item.get('expiry_date') else ""
                message += f"  • {item['name']}: {item['quantity']} {item['unit']}{expiry}\n"
            message += "\n"
        
        # Se il messaggio è troppo lungo, divide in più messaggi
        if len(message) > 4000:
            await update.message.reply_text(
                "📋 Il tuo inventario è molto ampio. Ecco un riepilogo per categorie:"
            )
            
            # Invia un messaggio per ogni categoria
            for category, items in categories.items():
                cat_message = f"*{category}:*\n"
                for item in items:
                    expiry = f" (Scad: {item['expiry_date']})" if item.get('expiry_date') else ""
                    cat_message += f"  • {item['name']}: {item['quantity']} {item['unit']}{expiry}\n"
                
                await update.message.reply_text(
                    cat_message,
                    parse_mode=ParseMode.MARKDOWN
                )
        else:
            await update.message.reply_text(
                message,
                parse_mode=ParseMode.MARKDOWN
            )
        
        # Pulsanti per interagire con l'inventario
        if inventory:
            # Mostra pulsanti per ogni alimento (massimo 10 per non sovraccaricare l'interfaccia)
            buttons = []
            for item in inventory[:10]:
                buttons.append([(f"{item['name']}", f"food_item:{item['id']}")])
            
            if len(inventory) > 10:
                buttons.append([("Vedi altri...", "more_inventory")])
            
            await update.message.reply_text(
                "Seleziona un alimento per vedere i dettagli:",
                reply_markup=get_inline_keyboard(buttons)
            )
        
        return INVENTORY_MENU
    
    async def show_expiring_items(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostra gli alimenti in scadenza."""
        user_id = update.effective_user.id
        
        # Ottieni gli alimenti in scadenza (prossimi 7 giorni)
        expiring_items = await self.data_manager.get_food_inventory(
            user_id=user_id, 
            expiring_soon=True, 
            days_threshold=7
        )
        
        if not expiring_items:
            await update.message.reply_text(
                "✅ Non hai alimenti in scadenza nei prossimi 7 giorni.",
                reply_markup=get_keyboard_markup(Menu.INVENTORY)
            )
            return INVENTORY_MENU
        
        # Crea il messaggio con gli alimenti in scadenza
        message = "⚠️ *Alimenti in scadenza:*\n\n"
        
        # Raggruppa per data di scadenza
        by_date = {}
        for item in expiring_items:
            expiry = item["expiry_date"]
            if expiry not in by_date:
                by_date[expiry] = []
            by_date[expiry].append(item)
        
        # Ordina per data di scadenza
        for expiry in sorted(by_date.keys()):
            # Converti la data in formato leggibile
            date_obj = datetime.datetime.strptime(expiry, "%Y-%m-%d").date()
            date_str = date_obj.strftime("%d/%m/%Y")
            
            message += f"*📅 {date_str}:*\n"
            
            for item in by_date[expiry]:
                message += f"  • {item['name']}: {item['quantity']} {item['unit']}\n"
            
            message += "\n"
        
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Pulsanti per interagire con gli alimenti in scadenza
        if expiring_items:
            buttons = []
            for item in expiring_items[:10]:
                buttons.append([(f"{item['name']}", f"food_item:{item['id']}")])
            
            await update.message.reply_text(
                "Seleziona un alimento per vedere i dettagli o modificarlo:",
                reply_markup=get_inline_keyboard(buttons)
            )
        
        return INVENTORY_MENU
    
    async def search_food_item(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Avvia la ricerca di un alimento nell'inventario."""
        await update.message.reply_text(
            "🔍 *Cerca Alimento*\n\n"
            "Inserisci il nome o parte del nome dell'alimento che stai cercando:",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Imposta il contesto di ricerca
        user_id = update.effective_user.id
        self.active_contexts[user_id] = "search_food"
        
        return MAIN_MENU
    
    # Funzioni per i piani alimentari
    
    async def start_add_meal_plan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Avvia il processo di creazione di un nuovo piano alimentare."""
        await update.message.reply_text(
            "🍽️ *Crea Nuovo Piano Alimentare*\n\n"
            "Inserisci un nome per il tuo nuovo piano:\n"
            "(oppure invia /cancel per annullare)",
            parse_mode=ParseMode.MARKDOWN
        )
        
        return ADD_MEAL_PLAN_NAME
    
    async def add_meal_plan_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce l'input del nome del piano alimentare."""
        context.user_data["meal_plan_name"] = update.message.text
        
        await update.message.reply_text(
            f"👍 Nome: {update.message.text}\n\n"
            f"Ora inserisci la data di inizio (formato GG/MM/AAAA):\n"
            f"(oppure invia /cancel per annullare)"
        )
        
        return ADD_MEAL_PLAN_START
    
    async def add_meal_plan_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce l'input della data di inizio del piano alimentare."""
        text = update.message.text
        
        # Prova a convertire la data
        try:
            # Supporta formati comuni
            if "/" in text:
                day, month, year = text.split('/')
                date_obj = datetime.date(int(year), int(month), int(day))
            elif "-" in text:
                parts = text.split('-')
                if len(parts[0]) == 4:  # AAAA-MM-GG
                    year, month, day = parts
                else:  # GG-MM-AAAA
                    day, month, year = parts
                date_obj = datetime.date(int(year), int(month), int(day))
            else:
                raise ValueError("Formato data non riconosciuto")
            
            # Converti in formato SQL (YYYY-MM-DD)
            context.user_data["meal_plan_start"] = date_obj.strftime("%Y-%m-%d")
            
            await update.message.reply_text(
                f"👍 Data di inizio: {date_obj.strftime('%d/%m/%Y')}\n\n"
                f"Ora inserisci la data di fine (formato GG/MM/AAAA):\n"
                f"(oppure invia /cancel per annullare)"
            )
            
            return ADD_MEAL_PLAN_END
        
        except (ValueError, IndexError):
            await update.message.reply_text(
                "❌ Formato data non valido.\n"
                "Per favore, inserisci la data nel formato GG/MM/AAAA:"
            )
            return ADD_MEAL_PLAN_START
    
    async def add_meal_plan_end(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce l'input della data di fine del piano alimentare."""
        text = update.message.text
        
        # Prova a convertire la data
        try:
            # Supporta formati comuni
            if "/" in text:
                day, month, year = text.split('/')
                date_obj = datetime.date(int(year), int(month), int(day))
            elif "-" in text:
                parts = text.split('-')
                if len(parts[0]) == 4:  # AAAA-MM-GG
                    year, month, day = parts
                else:  # GG-MM-AAAA
                    day, month, year = parts
                date_obj = datetime.date(int(year), int(month), int(day))
            else:
                raise ValueError("Formato data non riconosciuto")
            
            # Verifica che la data di fine sia successiva a quella di inizio
            start_date = datetime.datetime.strptime(
                context.user_data["meal_plan_start"], 
                "%Y-%m-%d"
            ).date()
            
            if date_obj < start_date:
                await update.message.reply_text(
                    "❌ La data di fine deve essere successiva alla data di inizio.\n"
                    "Per favore, inserisci una data valida:"
                )
                return ADD_MEAL_PLAN_END
            
            # Converti in formato SQL (YYYY-MM-DD)
            context.user_data["meal_plan_end"] = date_obj.strftime("%Y-%m-%d")
            
            await update.message.reply_text(
                f"👍 Data di fine: {date_obj.strftime('%d/%m/%Y')}\n\n"
                f"Per finire, aggiungi delle note o dettagli sul piano (opzionale):\n"
                f"(oppure scrivi 'nessuna' per saltare)\n"
                f"(oppure invia /cancel per annullare)"
            )
            
            return ADD_MEAL_PLAN_NOTES
        
        except (ValueError, IndexError):
            await update.message.reply_text(
                "❌ Formato data non valido.\n"
                "Per favore, inserisci la data nel formato GG/MM/AAAA:"
            )
            return ADD_MEAL_PLAN_END
    
    async def add_meal_plan_notes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce l'input delle note e completa la creazione del piano alimentare."""
        text = update.message.text
        
        if text.lower() in ["nessuna", "no", "n/a", "-"]:
            context.user_data["meal_plan_notes"] = None
        else:
            context.user_data["meal_plan_notes"] = text
        
        # Recupera i dati del piano alimentare
        user_id = update.effective_user.id
        name = context.user_data["meal_plan_name"]
        start_date = context.user_data["meal_plan_start"]
        end_date = context.user_data["meal_plan_end"]
        notes = context.user_data.get("meal_plan_notes")
        
        # Crea il piano alimentare
        plan_id = await self.data_manager.create_meal_plan(
            user_id=user_id,
            name=name,
            start_date=start_date,
            end_date=end_date,
            notes=notes
        )
        
        if plan_id:
            # Imposta il piano corrente
            self.current_plans[user_id] = plan_id
            
            # Formatta le date per la visualizzazione
            start_obj = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
            end_obj = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
            
            # Calcola la durata in giorni
            duration = (end_obj - start_obj).days + 1
            
            # Formatta le informazioni per la visualizzazione
            notes_text = f"\n📝 Note: {notes}" if notes else ""
            
            await update.message.reply_text(
                f"✅ *Piano alimentare creato!*\n\n"
                f"🍽️ {name}\n"
                f"📅 Dal {start_obj.strftime('%d/%m/%Y')} al {end_obj.strftime('%d/%m/%Y')}\n"
                f"⏱️ Durata: {duration} giorni"
                f"{notes_text}\n\n"
                f"Ora puoi aggiungere pasti a questo piano usando '🍳 Aggiungi Pasto'.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_keyboard_markup(Menu.MEAL_PLAN)
            )
        else:
            await update.message.reply_text(
                "❌ Si è verificato un errore durante la creazione del piano alimentare.\n"
                "Riprova più tardi.",
                reply_markup=get_keyboard_markup(Menu.MEAL_PLAN)
            )
        
        # Pulisci i dati dell'utente
        self._clear_user_data(user_id)
        
        return MEAL_PLAN_MENU
    
    async def start_add_meal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Avvia il processo di aggiunta di un pasto a un piano alimentare."""
        user_id = update.effective_user.id
        
        # Verifica se c'è un piano attivo
        if user_id in self.current_plans:
            plan_id = self.current_plans[user_id]
            context.user_data["meal_plan_id"] = plan_id
            
            # Ottieni i dettagli del piano
            plan = await self.data_manager.get_meal_plan(plan_id)
            
            if plan:
                await update.message.reply_text(
                    f"🍳 *Aggiungi Pasto a {plan['name']}*\n\n"
                    f"Inserisci la data del pasto (formato GG/MM/AAAA):\n"
                    f"(oppure invia /cancel per annullare)",
                    parse_mode=ParseMode.MARKDOWN
                )
                
                return ADD_MEAL_DATE
        
        # Se non c'è un piano attivo, mostra l'elenco dei piani disponibili
        plans = await self.data_manager.get_meal_plans(user_id, current_only=True)
        
        if not plans:
            # Nessun piano disponibile
            await update.message.reply_text(
                "❌ Non hai piani alimentari attivi.\n\n"
                "Crea prima un nuovo piano usando '➕ Nuovo Piano'.",
                reply_markup=get_keyboard_markup(Menu.MEAL_PLAN)
            )
            return MEAL_PLAN_MENU
        
        # Crea i pulsanti per la selezione del piano
        buttons = []
        for plan in plans:
            buttons.append([(plan["name"], f"select_plan:{plan['id']}")])
        
        await update.message.reply_text(
            "🍽️ *Seleziona un piano alimentare:*\n\n"
            "A quale piano vuoi aggiungere un pasto?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_inline_keyboard(buttons)
        )
        
        # Imposta il contesto
        self.active_contexts[user_id] = "select_plan_for_meal"
        
        return MEAL_PLAN_MENU
    
    async def add_meal_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce l'input della data del pasto."""
        text = update.message.text
        
        # Prova a convertire la data
        try:
            # Supporta formati comuni
            if "/" in text:
                day, month, year = text.split('/')
                date_obj = datetime.date(int(year), int(month), int(day))
            elif "-" in text:
                parts = text.split('-')
                if len(parts[0]) == 4:  # AAAA-MM-GG
                    year, month, day = parts
                else:  # GG-MM-AAAA
                    day, month, year = parts
                date_obj = datetime.date(int(year), int(month), int(day))
            else:
                raise ValueError("Formato data non riconosciuto")
            
            # Verifica che la data sia all'interno del periodo del piano
            plan_id = context.user_data["meal_plan_id"]
            plan = await self.data_manager.get_meal_plan(plan_id)
            
            start_date = datetime.datetime.strptime(plan["start_date"], "%Y-%m-%d").date()
            end_date = datetime.datetime.strptime(plan["end_date"], "%Y-%m-%d").date()
            
            if date_obj < start_date or date_obj > end_date:
                await update.message.reply_text(
                #!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
telegram_bot.py - Implementazione del bot Telegram per l'assistente personale

Questo modulo gestisce l'interfaccia utente tramite Telegram, definendo i comandi
disponibili e le callback per le interazioni con l'utente. Si integra con i moduli
anthropic_helper.py per l'interazione con Claude AI e data_manager.py per la
persistenza dei dati.
"""

import os
import logging
import asyncio
import json
import datetime
import re
from typing import Dict, List, Optional, Union, Any, Callable, Set, Tuple
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from functools import wraps
from uuid import uuid4

import httpx
from telegram import (
    Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup, 
    ReplyKeyboardMarkup, ReplyKeyboardRemove, ParseMode,
    BotCommand, InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters, CallbackContext
)
from telegram.constants import ChatAction
from telegram.error import TelegramError

from dotenv import load_dotenv

from anthropic_helper import AnthropicHelper, TextBlock, Message, Role, ImageBlock, ImageFormat
from data_manager import DataManager

# Caricamento variabili d'ambiente
load_dotenv()

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Costanti
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
DEFAULT_MODEL = os.getenv("CLAUDE_DEFAULT_MODEL", "claude-3-5-sonnet-20241022")
DATA_DIR = os.getenv("DATA_DIR", "data")
MAX_CONVERSATION_HISTORY = 10  # Numero massimo di messaggi da mantenere in cronologia
SYSTEM_PROMPT_PATH = "data/system_prompt.txt"

# Stati per ConversationHandler
(
    MAIN_MENU,
    WAITING_QUERY,
    INVENTORY_MENU,
    MEAL_PLAN_MENU,
    SHOPPING_LIST_MENU,
    HEALTH_MENU,
    ADD_FOOD_ITEM,
    ADD_FOOD_QUANTITY,
    ADD_FOOD_UNIT,
    ADD_FOOD_EXPIRY,
    ADD_FOOD_CATEGORY,
    ADD_FOOD_NOTES,
    ADD_MEAL_PLAN_NAME,
    ADD_MEAL_PLAN_START,
    ADD_MEAL_PLAN_END,
    ADD_MEAL_PLAN_NOTES,
    ADD_MEAL_DATE,
    ADD_MEAL_TYPE,
    ADD_MEAL_DESCRIPTION,
    ADD_MEAL_RECIPE,
    ADD_SHOPPING_LIST_NAME,
    ADD_SHOPPING_ITEM_NAME,
    ADD_SHOPPING_ITEM_QUANTITY,
    ADD_SHOPPING_ITEM_UNIT,
    ADD_SHOPPING_ITEM_CATEGORY,
    ADD_HEALTH_CONDITION_NAME,
    ADD_HEALTH_CONDITION_DESCRIPTION,
    ADD_DIETARY_RESTRICTION_NAME,
    ADD_DIETARY_RESTRICTION_FOOD,
    ADD_SUPPLEMENT_NAME,
    ADD_SUPPLEMENT_DOSAGE,
    ADD_SUPPLEMENT_FREQUENCY,
    ADD_HEALTH_REPORT_TYPE,
    ADD_HEALTH_REPORT_DATE,
    ADD_HEALTH_REPORT_SUMMARY,
    PROCESS_PHOTO,
    WAITING_CONFIRMATION,
) = range(31)

# Definizione dei menu principali
class Menu:
    """Definisce i menu principali e i submenu del bot."""
    
    MAIN = [
        ["🍽️ Piani Alimentari", "🥑 Inventario Alimenti"],
        ["🛒 Lista della Spesa", "🏥 Salute"],
        ["💬 Chiedi a Claude", "⚙️ Impostazioni"]
    ]
    
    INVENTORY = [
        ["➕ Aggiungi Alimento", "📋 Visualizza Inventario"],
        ["⚠️ In Scadenza", "🔍 Cerca Alimento"],
        ["🔙 Menu Principale"]
    ]
    
    MEAL_PLAN = [
        ["➕ Nuovo Piano", "📆 Piani Attuali"],
        ["🍳 Aggiungi Pasto", "📅 Pasti di Oggi"],
        ["🔍 Cerca Ricette", "📊 Analisi Nutrizionale"],
        ["🔙 Menu Principale"]
    ]
    
    SHOPPING_LIST = [
        ["➕ Nuova Lista", "📝 Liste Esistenti"],
        ["🛍️ Aggiungi Articolo", "🧾 Lista dalla Foto"],
        ["🤖 Genera da Inventario", "✅ Segna Completati"],
        ["🔙 Menu Principale"]
    ]
    
    HEALTH = [
        ["🩺 Condizioni Mediche", "🚫 Restrizioni Alimentari"],
        ["💊 Integratori", "📊 Referti"],
        ["🔍 Analisi Alimenti", "🔔 Promemoria"],
        ["🔙 Menu Principale"]
    ]
    
    SETTINGS = [
        ["👤 Profilo", "🌐 Preferenze Lingua"],
        ["🔄 Backup Dati", "📤 Esporta Dati"],
        ["🔙 Menu Principale"]
    ]


# Definizione degli handler per i comandi e le callback
def get_keyboard_markup(menu_buttons: List[List[str]]) -> ReplyKeyboardMarkup:
    """
    Crea una tastiera personalizzata per i menu.
    
    Args:
        menu_buttons: Lista di liste di stringhe per i pulsanti
        
    Returns:
        ReplyKeyboardMarkup: Markup della tastiera personalizzata
    """
    return ReplyKeyboardMarkup(
        menu_buttons,
        resize_keyboard=True,
        one_time_keyboard=False
    )


def get_inline_keyboard(buttons: List[List[Tuple[str, str]]]) -> InlineKeyboardMarkup:
    """
    Crea una tastiera inline per le callback.
    
    Args:
        buttons: Lista di liste di tuple (testo, callback_data)
        
    Returns:
        InlineKeyboardMarkup: Markup della tastiera inline
    """
    keyboard = []
    for row in buttons:
        keyboard_row = []
        for text, callback_data in row:
            keyboard_row.append(InlineKeyboardButton(text, callback_data=callback_data))
        keyboard.append(keyboard_row)
    
    return InlineKeyboardMarkup(keyboard)


class TelegramBot:
    """
    Classe principale per la gestione del bot Telegram.
    Gestisce tutte le interazioni con l'utente tramite l'interfaccia Telegram,
    integrando le funzionalità di Claude AI e la persistenza dei dati.
    """
    
    def __init__(self, token: str, admin_user_id: int = None):
        """
        Inizializza il bot Telegram.
        
        Args:
            token: Token del bot Telegram
            admin_user_id: ID dell'utente amministratore (opzionale)
        """
        self.token = token
        self.admin_user_id = admin_user_id
        
        # Inizializzazione dei componenti
        self.app = Application.builder().token(token).build()
        self.data_manager = None
        self.claude_helper = None
        
        # Dizionari per tenere traccia di stati e contesti
        self.conversation_history = {}  # {user_id: [Message]}
        self.user_data_temp = {}  # {user_id: {temp_data}}
        self.active_contexts = {}  # {user_id: current_context}
        self.current_plans = {}  # {user_id: current_meal_plan_id}
        self.current_lists = {}  # {user_id: current_shopping_list_id}
        
        # Carica il prompt di sistema
        self.system_prompt = self.load_system_prompt()
        
        # Registra gli handler
        self._register_handlers()
        
        logger.info("TelegramBot inizializzato")
    
    async def initialize_components(self):
        """Inizializza i componenti asincroni come data_manager e claude_helper."""
        # Inizializza il gestore del database
        self.data_manager = DataManager()
        await self.data_manager.initialize_database()
        await self.data_manager.schedule_regular_backups()
        
        # Inizializza l'helper di Anthropic
        self.claude_helper = AnthropicHelper(model=DEFAULT_MODEL)
        
        logger.info("Componenti inizializzati con successo")
    
    def load_system_prompt(self) -> str:
        """
        Carica il prompt di sistema da file.
        
        Returns:
            str: Testo del prompt di sistema
        """
        try:
            system_prompt_path = Path(SYSTEM_PROMPT_PATH)
            if system_prompt_path.exists():
                with open(system_prompt_path, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            else:
                # Prompt di sistema predefinito se il file non esiste
                default_prompt = (
                    "Sei un assistente per la gestione di piani alimentari, inventario "
                    "degli alimenti, liste della spesa e monitoraggio sanitario. "
                    "Aiuta l'utente a mantenere uno stile di vita sano, considerando "
                    "eventuali restrizioni alimentari e condizioni mediche. "
                    "Rispondi in modo conciso e utile."
                )
                logger.warning(f"File prompt di sistema non trovato: {SYSTEM_PROMPT_PATH}. "
                              f"Utilizzo prompt predefinito.")
                # Crea il file con il prompt predefinito
                os.makedirs(os.path.dirname(system_prompt_path), exist_ok=True)
                with open(system_prompt_path, 'w', encoding='utf-8') as f:
                    f.write(default_prompt)
                return default_prompt
        except Exception as e:
            logger.error(f"Errore nel caricamento del prompt di sistema: {str(e)}")
            return ("Sei un assistente per la gestione di piani alimentari e liste della spesa. "
                   "Fornisci risposte concise e utili.")
    
    def _register_handlers(self):
        """Registra tutti gli handler dei comandi e delle callback."""
        # Handler dei comandi principali
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CommandHandler("menu", self.cmd_menu))
        self.app.add_handler(CommandHandler("ask", self.cmd_ask))
        self.app.add_handler(CommandHandler("impostazioni", self.cmd_settings))
        self.app.add_handler(CommandHandler("reset", self.cmd_reset))
        
        # Handler del menu principale per pulsanti personalizzati
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self.handle_text_message
        ))
        
        # Handler per le foto
        self.app.add_handler(MessageHandler(
            filters.PHOTO,
            self.handle_photo
        ))
        
        # Handler per i documenti
        self.app.add_handler(MessageHandler(
            filters.Document.ALL,
            self.handle_document
        ))
        
        # Handler per le callback inline
        self.app.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # Handler per gli errori
        self.app.add_error_handler(self.error_handler)
        
        # ConversationHandler per l'aggiunta di alimenti all'inventario
        add_food_conv = ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex(r"^➕ Aggiungi Alimento$"),
                    self.start_add_food
                )
            ],
            states={
                ADD_FOOD_ITEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_food_name)],
                ADD_FOOD_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_food_quantity)],
                ADD_FOOD_UNIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_food_unit)],
                ADD_FOOD_EXPIRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_food_expiry)],
                ADD_FOOD_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_food_category)],
                ADD_FOOD_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_food_notes)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_conversation)]
        )
        self.app.add_handler(add_food_conv)
        
        # ConversationHandler per l'aggiunta di un piano alimentare
        add_meal_plan_conv = ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex(r"^➕ Nuovo Piano$"),
                    self.start_add_meal_plan
                )
            ],
            states={
                ADD_MEAL_PLAN_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_meal_plan_name)],
                ADD_MEAL_PLAN_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_meal_plan_start)],
                ADD_MEAL_PLAN_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_meal_plan_end)],
                ADD_MEAL_PLAN_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_meal_plan_notes)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_conversation)]
        )
        self.app.add_handler(add_meal_plan_conv)
        
        # ConversationHandler per l'aggiunta di un pasto
        add_meal_conv = ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex(r"^🍳 Aggiungi Pasto$"),
                    self.start_add_meal
                )
            ],
            states={
                ADD_MEAL_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_meal_date)],
                ADD_MEAL_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_meal_type)],
                ADD_MEAL_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_meal_description)],
                ADD_MEAL_RECIPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_meal_recipe)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_conversation)]
        )
        self.app.add_handler(add_meal_conv)
        
        # ConversationHandler per l'aggiunta di una lista della spesa
        add_shopping_list_conv = ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex(r"^➕ Nuova Lista$"),
                    self.start_add_shopping_list
                )
            ],
            states={
                ADD_SHOPPING_LIST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_shopping_list_name)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_conversation)]
        )
        self.app.add_handler(add_shopping_list_conv)
        
        # ConversationHandler per l'aggiunta di un articolo alla lista della spesa
        add_shopping_item_conv = ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex(r"^🛍️ Aggiungi Articolo$"),
                    self.start_add_shopping_item
                )
            ],
            states={
                ADD_SHOPPING_ITEM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_shopping_item_name)],
                ADD_SHOPPING_ITEM_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_shopping_item_quantity)],
                ADD_SHOPPING_ITEM_UNIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_shopping_item_unit)],
                ADD_SHOPPING_ITEM_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_shopping_item_category)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_conversation)]
        )
        self.app.add_handler(add_shopping_item_conv)
        
        # ConversationHandler per l'aggiunta di una condizione medica
        add_health_condition_conv = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.start_add_health_condition, pattern=r"^add_health_condition$")
            ],
            states={
                ADD_HEALTH_CONDITION_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_health_condition_name)],
                ADD_HEALTH_CONDITION_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_health_condition_description)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_conversation)]
        )
        self.app.add_handler(add_health_condition_conv)
        
        # ConversationHandler per l'aggiunta di una restrizione alimentare
        add_dietary_restriction_conv = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.start_add_dietary_restriction, pattern=r"^add_dietary_restriction$")
            ],
            states={
                ADD_DIETARY_RESTRICTION_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_dietary_restriction_name)],
                ADD_DIETARY_RESTRICTION_FOOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_dietary_restriction_food)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_conversation)]
        )
        self.app.add_handler(add_dietary_restriction_conv)
        
        # ConversationHandler per l'aggiunta di un integratore
        add_supplement_conv = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.start_add_supplement, pattern=r"^add_supplement$")
            ],
            states={
                ADD_SUPPLEMENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_supplement_name)],
                ADD_SUPPLEMENT_DOSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_supplement_dosage)],
                ADD_SUPPLEMENT_FREQUENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_supplement_frequency)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_conversation)]
        )
        self.app.add_handler(add_supplement_conv)
        
        # ConversationHandler per l'aggiunta di un referto medico
        add_health_report_conv = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.start_add_health_report, pattern=r"^add_health_report$")
            ],
            states={
                ADD_HEALTH_REPORT_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_health_report_type)],
                ADD_HEALTH_REPORT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_health_report_date)],
                ADD_HEALTH_REPORT_SUMMARY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_health_report_summary)],
                PROCESS_PHOTO: [
                    MessageHandler(filters.PHOTO, self.process_report_photo),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_report_without_photo)
                ],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_conversation)]
        )
        self.app.add_handler(add_health_report_conv)
        
        # ConversationHandler per la domanda a Claude
        ask_claude_conv = ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.Regex(r"^💬 Chiedi a Claude$"),
                    self.start_ask_claude
                )
            ],
            states={
                WAITING_QUERY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_claude_query),
                    MessageHandler(filters.PHOTO, self.process_claude_photo_query)
                ],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_conversation)]
        )
        self.app.add_handler(ask_claude_conv)
    
    async def set_bot_commands(self):
        """Imposta i comandi disponibili per il bot."""
        commands = [
            BotCommand("start", "Avvia il bot e mostra il messaggio di benvenuto"),
            BotCommand("menu", "Mostra il menu principale"),
            BotCommand("help", "Mostra l'elenco dei comandi disponibili"),
            BotCommand("ask", "Fai una domanda a Claude"),
            BotCommand("impostazioni", "Configura le preferenze del bot"),
            BotCommand("reset", "Ripristina la conversazione corrente")
        ]
        
        await self.app.bot.set_my_commands(commands)
        logger.info("Comandi del bot impostati")
    
    @asynccontextmanager
    async def show_typing(self, update: Update):
        """
        Context manager per mostrare l'indicatore di digitazione.
        
        Args:
            update: Oggetto Update di Telegram
        """
        try:
            chat_id = update.effective_chat.id
            await self.app.bot.send_chat_action(chat_id, ChatAction.TYPING)
            # Inizia un compito asincrono per mantenere l'azione di chat
            task = asyncio.create_task(self._keep_typing(chat_id))
            yield
        finally:
            # Termina il compito quando il context manager esce
            task.cancel()
    
    async def _keep_typing(self, chat_id: int):
        """
        Mantiene l'indicatore di digitazione attivo per chat lunghe.
        
        Args:
            chat_id: ID della chat
        """
        try:
            while True:
                await self.app.bot.send_chat_action(chat_id, ChatAction.TYPING)
                await asyncio.sleep(4.5)  # Le azioni di chat scadono dopo 5 secondi
        except asyncio.CancelledError:
            # Normale quando il compito viene cancellato
            pass
        except Exception as e:
            logger.warning(f"Errore nell'indicatore di digitazione: {str(e)}")
    
    async def _get_user_health_context(self, user_id: int) -> str:
        """
        Ottiene informazioni sanitarie dell'utente per il contesto.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            str: Stringa con informazioni sulle condizioni e restrizioni
        """
        try:
            conditions = await self.data_manager.get_health_conditions(user_id)
            restrictions = await self.data_manager.get_dietary_restrictions(user_id)
            supplements = await self.data_manager.get_supplements(user_id)
            
            context = []
            
            if conditions:
                condition_list = ", ".join([c["name"] for c in conditions])
                context.append(f"Condizioni mediche: {condition_list}")
            
            if restrictions:
                restriction_list = ", ".join([f"{r['name']} ({r['food_type']})" for r in restrictions])
                context.append(f"Restrizioni alimentari: {restriction_list}")
            
            if supplements:
                supplement_list = ", ".join([f"{s['name']} ({s['dosage']} {s['frequency']})" for s in supplements])
                context.append(f"Integratori: {supplement_list}")
            
            if context:
                return "\n".join(context)
            else:
                return "Nessuna informazione sanitaria disponibile."
                
        except Exception as e:
            logger.error(f"Errore nel recupero del contesto sanitario: {str(e)}")
            return "Errore nel recupero delle informazioni sanitarie."
    
    def _clear_user_data(self, user_id: int):
        """
        Pulisce i dati temporanei dell'utente.
        
        Args:
            user_id: ID dell'utente
        """
        if user_id in self.user_data_temp:
            self.user_data_temp[user_id] = {}
    
    def _add_to_conversation_history(self, user_id: int, role: Role, content: str):
        """
        Aggiunge un messaggio alla cronologia della conversazione.
        
        Args:
            user_id: ID dell'utente
            role: Ruolo del messaggio (user/assistant)
            content: Contenuto del messaggio
        """
        if user_id not in self.conversation_history:
            self.conversation_history[user_id] = []
        
        # Crea un nuovo messaggio
        message = Message(
            role=role,
            content=[TextBlock(text=content)]
        )
        
        # Aggiungi il messaggio alla cronologia
        self.conversation_history[user_id].append(message)
        
        # Limita la dimensione della cronologia
        if len(self.conversation_history[user_id]) > MAX_CONVERSATION_HISTORY:
            self.conversation_history[user_id] = self.conversation_history[user_id][-MAX_CONVERSATION_HISTORY:]
    
    def _get_conversation_history(self, user_id: int) -> List[Message]:
        """
        Ottiene la cronologia della conversazione per un utente.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            List[Message]: Lista di messaggi nella cronologia
        """
        return self.conversation_history.get(user_id, [])
    
    async def start_bot(self):
        """Avvia il bot Telegram."""
        # Inizializza i componenti
        await self.initialize_components()
        
        # Imposta i comandi del bot
        await self.set_bot_commands()
        
        # Avvia il polling
        logger.info("Avvio del bot Telegram...")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        
        try:
            # Mantieni in esecuzione finché non viene interrotto
            await self.app.updater.wait_closed()
        finally:
            # Pulizia alla chiusura
            await self.app.stop()
            await self.app.shutdown()
    
    async def stop_bot(self):
        """Ferma il bot Telegram."""
        logger.info("Arresto del bot Telegram...")
        await self.app.stop()
        await self.app.shutdown()
    
    # Handler degli errori
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce gli errori occorsi durante l'esecuzione."""
        logger.error(f"Errore durante l'esecuzione: {context.error}")
        
        # Se l'aggiornamento è disponibile, invia un messaggio di errore
        if update and hasattr(update, 'effective_chat'):
            await self.app.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Si è verificato un errore. Per favore riprova più tardi o contatta l'amministratore."
            )
        
        # Notifica all'amministratore in caso di errori critici
        if self.admin_user_id:
            error_message = f"❗ ERRORE: {context.error}\n\n"
            if update:
                if hasattr(update, 'effective_user'):
                    error_message += f"Utente: {update.effective_user.id} ({update.effective_user.full_name})\n"
                if hasattr(update, 'effective_message') and update.effective_message:
                    error_message += f"Messaggio: {update.effective_message.text}\n"
            
            try:
                await self.app.bot.send_message(
                    chat_id=self.admin_user_id,
                    text=error_message
                )
            except:
                logger.error("Impossibile inviare notifica di errore all'amministratore")
    
    # Handler dei comandi
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /start."""
        user = update.effective_user
        logger.info(f"Comando /start da utente {user.id} ({user.full_name})")
        
        welcome_message = (
            f"👋 Ciao {user.first_name}!\n\n"
            f"Benvenuto al tuo assistente personale per la gestione di:\n"
            f"• 🍽️ Piani alimentari\n"
            f"• 🥑 Inventario alimenti\n"
            f"• 🛒 Liste della spesa\n"
            f"• 🏥 Monitoraggio salute\n\n"
            f"Puoi interagire con me tramite il menu qui sotto o usando i comandi.\n"
            f"Digita /help per vedere tutti i comandi disponibili."
        )
        
        # Invia il messaggio di benvenuto con il menu principale
        await update.message.reply_text(
            welcome_message,
            reply_markup=get_keyboard_markup(Menu.MAIN)
        )
        
        return MAIN_MENU
    
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /help."""
        help_message = (
            "🔍 *Comandi Disponibili*\n\n"
            "/start - Avvia il bot e mostra il benvenuto\n"
            "/menu - Mostra il menu principale\n"
            "/help - Mostra questa guida\n"
            "/ask - Fai una domanda a Claude\n"
            "/impostazioni - Configura le preferenze\n"
            "/reset - Ripristina la conversazione\n\n"
            "📱 *Menu Principali*\n\n"
            "• 🍽️ *Piani Alimentari* - Gestisci i tuoi piani e pasti\n"
            "• 🥑 *Inventario Alimenti* - Tieni traccia degli alimenti disponibili\n"
            "• 🛒 *Lista della Spesa* - Crea e gestisci liste della spesa\n"
            "• 🏥 *Salute* - Monitora condizioni e integratori\n"
            "• 💬 *Chiedi a Claude* - Assistenza personalizzata\n"
            "• ⚙️ *Impostazioni* - Configura l'assistente\n\n"
            "Usa i pulsanti del menu per navigare facilmente tra le funzioni."
        )
        
        await update.message.reply_text(
            help_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_keyboard_markup(Menu.MAIN)
        )
    
    async def cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /menu."""
        await update.message.reply_text(
            "🔍 Seleziona un'opzione dal menu:",
            reply_markup=get_keyboard_markup(Menu.MAIN)
        )
        
        return MAIN_MENU
    
    async def cmd_ask(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /ask."""
        await update.message.reply_text(
            "💬 Cosa vuoi chiedere a Claude?\n"
            "Puoi fare domande su alimentazione, piani pasto, ricette, o qualsiasi altro argomento."
        )
        
        return WAITING_QUERY
    
    async def cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /impostazioni."""
        settings_buttons = [
            [("👤 Profilo", "settings_profile"), ("🌐 Lingua", "settings_language")],
            [("🔄 Backup", "settings_backup"), ("📤 Esporta", "settings_export")]
        ]
        
        await update.message.reply_text(
            "⚙️ *Impostazioni*\n\n"
            "Seleziona un'opzione per configurare l'assistente:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_inline_keyboard(settings_buttons)
        )
    
    async def cmd_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce il comando /reset."""
        user_id = update.effective_user.id
        
        # Resetta la conversazione
        if user_id in self.conversation_history:
            self.conversation_history[user_id] = []
        
        # Resetta i dati temporanei
        self._clear_user_data(user_id)
        
        await update.message.reply_text(
            "🔄 La conversazione è stata resettata.\n"
            "Puoi iniziare una nuova interazione.",
            reply_markup=get_keyboard_markup(Menu.MAIN)
        )
        
        return MAIN_MENU
    
    # Handler per i messaggi di testo
    
    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Gestisce i messaggi di testo non associati a comandi specifici.
        Analizza il testo e indirizza alla funzione appropriata in base al contenuto.
        """
        text = update.message.text
        user_id = update.effective_user.id
        
        # Gestione dei menu principali
        if text == "🍽️ Piani Alimentari":
            return await self.show_meal_plan_menu(update, context)
        elif text == "🥑 Inventario Alimenti":
            return await self.show_inventory_menu(update, context)
        elif text == "🛒 Lista della Spesa":
            return await self.show_shopping_list_menu(update, context)
        elif text == "🏥 Salute":
            return await self.show_health_menu(update, context)
        elif text == "💬 Chiedi a Claude":
            return await self.start_ask_claude(update, context)
        elif text == "⚙️ Impostazioni":
            return await self.cmd_settings(update, context)
        elif text == "🔙 Menu Principale":
            return await self.cmd_menu(update, context)
        
        # Gestione inventario
        elif text == "📋 Visualizza Inventario":
            return await self.show_inventory(update, context)
        elif text == "⚠️ In Scadenza":
            return await self.show_expiring_items(update, context)
        elif text == "🔍 Cerca Alimento":
            return await self.search_food_item(update, context)
        
        # Gestione piani alimentari
        elif text == "📆 Piani Attuali":
            return await self.show_current_meal_plans(update, context)
        elif text == "📅 Pasti di Oggi":
            return await self.show_today_meals(update, context)
        elif text == "🔍 Cerca Ricette":
            return await self.search_recipes(update, context)
        elif text == "📊 Analisi Nutrizionale":
            return await self.show_nutrition_analysis(update, context)
        
        # Gestione liste della spesa
        elif text == "📝 Liste Esistenti":
            return await self.show_shopping_lists(update, context)
        elif text == "🧾 Lista dalla Foto":
            return await self.start_shopping_list_from_photo(update, context)
        elif text == "🤖 Genera da Inventario":
            return await self.generate_shopping_list(update, context)
        elif text == "✅ Segna Completati":
            return await self.mark_shopping_items(update, context)
        
        # Se il messaggio non corrisponde a nessun comando specifico
        # e l'utente è in modalità conversazione con Claude
        if self.active_contexts.get(user_id) == "claude":
            return await self.process_claude_query(update, context)
        
        # Altrimenti, chiedi a Claude di interpretare il messaggio
        async with self.show_typing(update):
            # Crea un messaggio per Claude che chiede di interpretare l'input
            user_intent_query = (
                f"L'utente ha inviato questo messaggio: \"{text}\"\n"
                f"Determina l'intento dell'utente tra queste opzioni:\n"
                f"1. Domanda su alimentazione o nutrizione\n"
                f"2. Richiesta di ricetta o piano alimentare\n" 
                f"3. Domanda su salute o integratori\n"
                f"4. Richiesta di aggiungere qualcosa all'inventario\n"
                f"5. Richiesta di aggiungere qualcosa alla lista della spesa\n"
                f"6. Altra richiesta\n\n"
                f"Rispondi solo con il numero dell'opzione più probabile."
            )
            
            intent_response = await self.claude_helper.simple_query(user_intent_query)
            intent_number = re.search(r'(\d+)', intent_response)
            
            if intent_number:
                intent = int(intent_number.group(1))
                
                if intent == 1 or intent == 2 or intent == 3:
                    # Domande relative a alimentazione, ricette o salute
                    self._add_to_conversation_history(user_id, Role.USER, text)
                    return await self.process_claude_query(update, context)
                elif intent == 4:
                    # Probabilmente vuole aggiungere all'inventario
                    context.user_data["food_name"] = text
                    await update.message.reply_text(
                        f"Ho capito che vuoi aggiungere \"{text}\" all'inventario.\n"
                        f"Qual è la quantità?"
                    )
                    return ADD_FOOD_QUANTITY
                elif intent == 5:
                    # Probabilmente vuole aggiungere alla lista della spesa
                    context.user_data["shopping_item"] = text
                    
                    # Verifica se c'è una lista della spesa attiva
                    if user_id in self.current_lists:
                        list_id = self.current_lists[user_id]
                        
                        # Aggiungi direttamente alla lista corrente
                        item_id = await self.data_manager.add_shopping_item(
                            list_id=list_id,
                            name=text,
                            category="Generale"
                        )
                        
                        if item_id:
                            await update.message.reply_text(
                                f"✅ \"{text}\" aggiunto alla lista della spesa corrente."
                            )
                        else:
                            await update.message.reply_text(
                                "❌ Errore nell'aggiunta dell'articolo. Riprova più tardi."
                            )
                    else:
                        # Chiedi all'utente di selezionare una lista
                        shopping_lists = await self.data_manager.get_shopping_lists(user_id)
                        
                        if not shopping_lists:
                            # Crea una nuova lista
                            list_id = await self.data_manager.create_shopping_list(
                                user_id=user_id,
                                name=f"Lista {datetime.datetime.now().strftime('%d/%m/%Y')}"
                            )
                            
                            self.current_lists[user_id] = list_id
                            
                            item_id = await self.data_manager.add_shopping_item(
                                list_id=list_id,
                                name=text,
                                category="Generale"
                            )
                            
                            await update.message.reply_text(
                                f"✅ Ho creato una nuova lista della spesa e aggiunto \"{text}\"."
                            )
                        else:
                            # Mostra le liste disponibili
                            buttons = []
                            for l in shopping_lists:
                                buttons.append([(l["name"], f"select_list:{l['id']}")])
                            
                            await update.message.reply_text(
                                f"A quale lista della spesa vuoi aggiungere \"{text}\"?",
                                reply_markup=get_inline_keyboard(buttons)
                            )
                            
                            # Salva l'articolo nei dati temporanei
                            self.user_data_temp[user_id] = {"pending_item": text}
                    
                    return MAIN_MENU
                else:
                    # Intento non chiaro o non specifico, usa Claude per rispondere
                    self._add_to_conversation_history(user_id, Role.USER, text)
                    return await self.process_claude_query(update, context)
            else:
                # Se non riesce a determinare l'intento, usa Claude per rispondere
                self._add_to_conversation_history(user_id, Role.USER, text)
                return await self.process_claude_query(update, context)
    
    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce le foto inviate dall'utente."""
        user_id = update.effective_user.id
        
        # Se l'utente è in un contesto specifico che accetta foto
        context_key = self.active_contexts.get(user_id)
        
        if context_key == "shopping_list_photo":
            # Elabora la foto della lista della spesa
            return await self.process_shopping_list_photo(update, context)
        elif context_key == "food_photo":
            # Elabora la foto dell'alimento
            return await self.process_food_photo(update, context)
        elif context_key == "health_report":
            # Elabora la foto del referto
            return await self.process_report_photo(update, context)
        elif context_key == "claude" or not context_key:
            # Inoltra la foto a Claude con richiesta di analisi
            return await self.process_claude_photo_query(update, context)
        else:
            # Contesto non riconosciuto
            await update.message.reply_text(
                "📸 Non so come elaborare questa foto nel contesto attuale.\n"
                "Se vuoi analizzarla, prova a usare '💬 Chiedi a Claude' e invia la foto con una domanda."
            )
    
    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce i documenti inviati dall'utente."""
        user_id = update.effective_user.id
        document = update.message.document
        
        # Verifica il tipo di documento
        if document.mime_type in ['image/jpeg', 'image/png', 'image/jpg']:
            # Scarica il documento come foto
            file = await context.bot.get_file(document.file_id)
            photo_bytes = await file.download_as_bytearray()
            
            # Salva temporaneamente
            context.user_data["photo_data"] = BytesIO(photo_bytes)
            
            # Gestisci come una foto
            context_key = self.active_contexts.get(user_id)
            
            if context_key == "shopping_list_photo":
                return await self.process_shopping_list_photo(update, context, from_document=True)
            elif context_key == "food_photo":
                return await self.process_food_photo(update, context, from_document=True)
            elif context_key == "health_report":
                return await self.process_report_photo(update, context, from_document=True)
            else:
                # Chiedi all'utente cosa vuole fare con l'immagine
                buttons = [
                    [("Analizza contenuto", "analyze_image")],
                    [("Analizza alimento", "analyze_food")],
                    [("Riconosci lista spesa", "recognize_list")]
                ]
                
                await update.message.reply_text(
                    "📄 Ho ricevuto la tua immagine. Cosa vorresti fare con essa?",
                    reply_markup=get_inline_keyboard(buttons)
                )
        
        elif document.mime_type in ['application/pdf', 'text/plain', 'application/msword', 
                                  'application/vnd.openxmlformats-officedocument.wordprocessingml.document']:
            # Documenti potenzialmente contenenti referti medici o piani alimentari
            buttons = [
                [("Referto medico", "process_report_document")],
                [("Piano alimentare", "process_meal_plan_document")],
                [("Altro documento", "process_other_document")]
            ]
            
            await update.message.reply_text(
                f"📄 Ho ricevuto il tuo documento '{document.file_name}'. Di che tipo di documento si tratta?",
                reply_markup=get_inline_keyboard(buttons)
            )
            
            # Salva l'ID del file per elaborazione successiva
            context.user_data["document_file_id"] = document.file_id
            context.user_data["document_name"] = document.file_name
        
        else:
            # Tipo di documento non supportato
            await update.message.reply_text(
                f"❌ Il tipo di documento '{document.mime_type}' non è attualmente supportato.\n"
                f"Puoi inviare immagini, PDF o documenti di testo."
            )
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gestisce le callback dai pulsanti inline."""
        query = update.callback_query
        await query.answer()  # Risponde alla callback per rimuovere l'indicatore di caricamento
        
        callback_data = query.data
        user_id = update.effective_user.id
        
        # Estrai il comando e i parametri dalla callback
        parts = callback_data.split(':')
        command = parts[0]
        params = parts[1:] if len(parts) > 1 else []
        
        # Gestione liste della spesa
        if command == "select_list":
            if len(params) > 0:
                list_id = int(params[0])
                self.current_lists[user_id] = list_id
                
                # Verifica se c'è un articolo in sospeso
                if user_id in self.user_data_temp and "pending_item" in self.user_data_temp[user_id]:
                    item_name = self.user_data_temp[user_id]["pending_item"]
                    
                    item_id = await self.data_manager.add_shopping_item(
                        list_id=list_id,
                        name=item_name,
                        category="Generale"
                    )
                    
                    await query.edit_message_text(
                        f"✅ \"{item_name}\" aggiunto alla lista della spesa."
                    )
                    
                    # Pulisci i dati temporanei
                    del self.user_data_temp[user_id]["pending_item"]
                else:
                    await query.edit_message_text(
                        f"✅ Lista della spesa selezionata. Ora puoi aggiungere articoli."
                    )
        
        # Gestione piani alimentari
        elif command == "select_plan":
            if len(params) > 0:
                plan_id = int(params[0])
                self.current_plans[user_id] = plan_id
                
                await query.edit_message_text(
                    f"✅ Piano alimentare selezionato. Ora puoi aggiungere pasti o visualizzare dettagli."
                )
        
        # Gestione degli elementi dell'inventario
        elif command == "food_item":
            if len(params) > 0:
                item_id = int(params[0])
                food_item = await self.data_manager.get_food_item(item_id)
                
                if food_item:
                    # Mostra dettagli dell'alimento
                    expiry_text = f"📅 Scadenza: {food_item['expiry_date']}\n" if food_item.get('expiry_date') else ""
                    notes_text = f"📝 Note: {food_item['notes']}\n" if food_item.get('notes') else ""
                    
                    message = (
                        f"🥑 *{food_item['name']}*\n\n"
                        f"🔢 Quantità: {food_item['quantity']} {food_item['unit']}\n"
                        f"🏷️ Categoria: {food_item['category']}\n"
                        f"{expiry_text}"
                        f"{notes_text}"
                    )
                    
                    # Pulsanti per le azioni
                    buttons = [
                        [("✏️ Modifica", f"edit_food:{item_id}"), ("🗑️ Elimina", f"delete_food:{item_id}")],
                        [("➕ Aggiorna quantità", f"update_food_quantity:{item_id}")]
                    ]
                    
                    await query.edit_message_text(
                        message,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=get_inline_keyboard(buttons)
                    )
                else:
                    await query.edit_message_text(
                        "❌ Alimento non trovato. Potrebbe essere stato rimosso."
                    )
        
        # Impostazioni
        elif command.startswith("settings_"):
            setting_type = command.replace("settings_", "")
            
            if setting_type == "profile":
                await query.edit_message_text(
                    "👤 *Profilo Utente*\n\n"
                    "Qui puoi gestire le tue informazioni personali e preferenze.",
                    parse_mode=ParseMode.MARKDOWN
                )
            
            elif setting_type == "language":
                language_buttons = [
                    [("🇮🇹 Italiano", "set_language:it"), ("🇬🇧 English", "set_language:en")],
                    [("🇪🇸 Español", "set_language:es"), ("🇫🇷 Français", "set_language:fr")]
                ]
                
                await query.edit_message_text(
                    "🌐 *Seleziona la Lingua*\n\n"
                    "Scegli la lingua che preferisci per l'interfaccia del bot:",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_inline_keyboard(language_buttons)
                )
            
            elif setting_type == "backup":
                backup_buttons = [
                    [("🔄 Crea Backup", "create_backup")],
                    [("📋 Lista Backup", "list_backups")],
                    [("🔙 Torna alle Impostazioni", "back_to_settings")]
                ]
                
                await query.edit_message_text(
                    "🔄 *Gestione Backup*\n\n"
                    "Puoi creare backup dei tuoi dati o ripristinarne uno precedente.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_inline_keyboard(backup_buttons)
                )
            
            elif setting_type == "export":
                export_buttons = [
                    [("📤 Esporta Tutto", "export_all")],
                    [("🥑 Solo Inventario", "export_inventory")],
                    [("🍽️ Solo Piani Alimentari", "export_meal_plans")],
                    [("🔙 Torna alle Impostazioni", "back_to_settings")]
                ]
                
                await query.edit_message_text(
                    "📤 *Esportazione Dati*\n\n"
                    "Scegli quali dati vuoi esportare:",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_inline_keyboard(export_buttons)
                )
        
        # Operazioni sull'inventario
        elif command == "edit_food":
            if len(params) > 0:
                item_id = int(params[0])
                food_item = await self.data_manager.get_food_item(item_id)
                
                if food_item:
                    # Salva l'ID dell'elemento nei dati utente
                    context.user_data["edit_food_id"] = item_id
                    
                    # Mostra form di modifica
                    message = (
                        f"✏️ *Modifica {food_item['name']}*\n\n"
                        f"Seleziona cosa vuoi modificare:"
                    )
                    
                    buttons = [
                        [("📝 Nome", f"edit_food_field:{item_id}:name")],
                        [("🔢 Quantità", f"edit_food_field:{item_id}:quantity")],
                        [("📏 Unità", f"edit_food_field:{item_id}:unit")],
                        [("🏷️ Categoria", f"edit_food_field:{item_id}:category")],
                        [("📅 Scadenza", f"edit_food_field:{item_id}:expiry_date")],
                        [("📝 Note", f"edit_food_field:{item_id}:notes")]
                    ]
                    
                    await query.edit_message_text(
                        message,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=get_inline_keyboard(buttons)
                    )
                else:
                    await query.edit_message_text(
                        "❌ Alimento non trovato. Potrebbe essere stato rimosso."
                    )
        
        elif command == "delete_food":
            if len(params) > 0:
                item_id = int(params[0])
                food_item = await self.data_manager.get_food_item(item_id)
                
                if food_item:
                    # Chiedi conferma
                    buttons = [
                        [("✅ Sì, elimina", f"confirm_delete_food:{item_id}")],
                        [("❌ No, annulla", f"cancel_delete_food:{item_id}")]
                    ]
                    
                    await query.edit_message_text(
                        f"⚠️ Sei sicuro di voler eliminare *{food_item['name']}* dall'inventario?",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=get_inline_keyboard(buttons)
                    )
                else:
                    await query.edit_message_text(
                        "❌ Alimento non trovato. Potrebbe essere stato rimosso."
                    )
        
        elif command == "confirm_delete_food":
            if len(params) > 0:
                item_id = int(params[0])
                result = await self.data_manager.delete_food_item(item_id)
                
                if result:
                    await query.edit_message_text(
                        "✅ Alimento eliminato con successo dall'inventario."
                    )
                else:
                    await query.edit_message_text(
                        "❌ Errore durante l'eliminazione. Riprova più tardi."
                    )
        
        elif command == "cancel_delete_food":
            if len(params) > 0:
                item_id = int(params[0])
                food_item = await self.data_manager.get_food_item(item_id)
                
                if food_item:
                    expiry_text = f"📅 Scadenza: {food_item['expiry_date']}\n" if food_item.get('expiry_date') else ""
                    notes_text = f"📝 Note: {food_item['notes']}\n" if food_item.get('notes') else ""
                    
                    message = (
                        f"🥑 *{food_item['name']}*\n\n"
                        f"🔢 Quantità: {food_item['quantity']} {food_item['unit']}\n"
                        f"🏷️ Categoria: {food_item['category']}\n"
                        f"{expiry_text}"
                        f"{notes_text}"
                    )
                    
                    # Pulsanti per le azioni
                    buttons = [
                        [("✏️ Modifica", f"edit_food:{item_id}"), ("🗑️ Elimina", f"delete_food:{item_id}")],
                        [("➕ Aggiorna quantità", f"update_food_quantity:{item_id}")]
                    ]
                    
                    await query.edit_message_text(
                        message,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=get_inline_keyboard(buttons)
                    )
                else:
                    await query.edit_message_text(
                        "❌ Alimento non trovato. Potrebbe essere stato rimosso."
                    )
        
        # Operazioni sulle immagini
        elif command == "analyze_image" and "photo_data" in context.user_data:
            # Usa la foto per analisi generica
            self.active_contexts[user_id] = "claude"
            
            await query.edit_message_text(
                "🔍 