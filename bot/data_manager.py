#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data_manager.py - Gestore del database per l'assistente personale

Questo modulo gestisce tutte le operazioni relative al database SQLite, 
inclusi creazione, aggiornamento, backup e migrazioni. Fornisce un'interfaccia
strutturata per l'accesso ai dati persistenti dell'applicazione.
"""

import os
import sqlite3
import json
import logging
import asyncio
import datetime
import shutil
from typing import Dict, List, Optional, Union, Any, Tuple
from pathlib import Path
from contextlib import contextmanager

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Costanti
DEFAULT_DB_FILENAME = "assistant_data.db"
DEFAULT_DATA_DIR = "data"
MIGRATIONS_DIR = "data/migrations"
BACKUP_DIR = "data/backups"
SCHEMA_FILE = "data/schema.sql"
BACKUP_RETENTION_DAYS = 7
BACKUP_INTERVAL_HOURS = 24


class DatabaseException(Exception):
    """Eccezione personalizzata per errori relativi al database."""
    pass


class DataManager:
    """
    Classe principale per la gestione del database SQLite.
    Fornisce metodi per l'accesso ai dati persistenti dell'applicazione.
    """
    
    def __init__(self, db_path: Optional[str] = None, data_dir: Optional[str] = None):
        """
        Inizializza il gestore del database.
        
        Args:
            db_path: Percorso del file database (se None, usa il percorso predefinito)
            data_dir: Directory principale per i dati (se None, usa la directory predefinita)
        """
        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self.migrations_dir = Path(MIGRATIONS_DIR)
        self.backup_dir = Path(BACKUP_DIR)
        
        # Crea le directory necessarie se non esistono
        self._ensure_directories()
        
        # Imposta il percorso del database
        self.db_path = Path(db_path or self.data_dir / DEFAULT_DB_FILENAME)
        
        # Variabile per tenere traccia degli eventi di backup pianificati
        self._scheduled_backup_task = None
        
        logger.info(f"DataManager inizializzato con database: {self.db_path}")
    
    def _ensure_directories(self):
        """Crea le directory necessarie se non esistono."""
        for directory in [self.data_dir, self.migrations_dir, self.backup_dir]:
            directory.mkdir(parents=True, exist_ok=True)
    
    @contextmanager
    def get_connection(self):
        """
        Context manager per ottenere una connessione al database.
        
        Yields:
            sqlite3.Connection: Connessione al database
        """
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            # Abilita il supporto per chiavi esterne
            conn.execute("PRAGMA foreign_keys = ON")
            # Configura per restituire righe come dizionari
            conn.row_factory = sqlite3.Row
            yield conn
        except sqlite3.Error as e:
            logger.error(f"Errore durante la connessione al database: {str(e)}")
            raise DatabaseException(f"Errore del database: {str(e)}")
        finally:
            if conn:
                conn.close()
    
    def initialize_database(self) -> bool:
        """
        Inizializza il database con lo schema base se non esiste già.
        
        Returns:
            bool: True se inizializzato con successo, False altrimenti
        """
        if self.db_path.exists():
            logger.info("Il database esiste già, verifica aggiornamenti...")
            return self.apply_migrations()
        
        try:
            # Controlla se esiste lo schema SQL
            schema_path = Path(SCHEMA_FILE)
            if not schema_path.exists():
                logger.error(f"File di schema {schema_path} non trovato")
                return False
            
            # Leggi lo schema SQL
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema_sql = f.read()
            
            # Crea il database con lo schema
            with self.get_connection() as conn:
                conn.executescript(schema_sql)
                conn.commit()
            
            logger.info("Database inizializzato con successo")
            return True
            
        except Exception as e:
            logger.error(f"Errore durante l'inizializzazione del database: {str(e)}")
            return False
    
    def apply_migrations(self) -> bool:
        """
        Applica le migrazioni disponibili in ordine di versione.
        
        Returns:
            bool: True se le migrazioni sono state applicate con successo, False altrimenti
        """
        try:
            # Crea la tabella di tracciamento migrazioni se non esiste
            with self.get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS migrations (
                        id INTEGER PRIMARY KEY,
                        version TEXT NOT NULL UNIQUE,
                        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
            
            # Ottieni le migrazioni già applicate
            applied_migrations = self.get_applied_migrations()
            
            # Trova tutte le migrazioni disponibili nella directory
            available_migrations = []
            for file_path in sorted(self.migrations_dir.glob("*.sql")):
                version = file_path.stem
                if version not in applied_migrations:
                    available_migrations.append((version, file_path))
            
            if not available_migrations:
                logger.info("Nessuna nuova migrazione da applicare")
                return True
            
            # Applica le migrazioni in ordine
            for version, file_path in available_migrations:
                self.apply_single_migration(version, file_path)
            
            logger.info(f"Applicate {len(available_migrations)} migrazioni con successo")
            return True
            
        except Exception as e:
            logger.error(f"Errore durante l'applicazione delle migrazioni: {str(e)}")
            return False
    
    def get_applied_migrations(self) -> List[str]:
        """
        Ottiene la lista delle migrazioni già applicate.
        
        Returns:
            List[str]: Lista delle versioni delle migrazioni applicate
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT version FROM migrations ORDER BY id")
                return [row['version'] for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Errore durante il recupero delle migrazioni applicate: {str(e)}")
            return []
    
    def apply_single_migration(self, version: str, file_path: Path) -> bool:
        """
        Applica una singola migrazione.
        
        Args:
            version: Versione della migrazione
            file_path: Percorso del file SQL della migrazione
            
        Returns:
            bool: True se la migrazione è stata applicata con successo, False altrimenti
        """
        try:
            logger.info(f"Applicazione della migrazione {version}...")
            
            # Leggi lo script SQL della migrazione
            with open(file_path, 'r', encoding='utf-8') as f:
                migration_sql = f.read()
            
            # Applica la migrazione in una transazione
            with self.get_connection() as conn:
                # Inizia una transazione
                conn.execute("BEGIN TRANSACTION")
                
                try:
                    # Esegui lo script di migrazione
                    conn.executescript(migration_sql)
                    
                    # Registra la migrazione come applicata
                    conn.execute(
                        "INSERT INTO migrations (version) VALUES (?)",
                        (version,)
                    )
                    
                    # Commit della transazione
                    conn.commit()
                    logger.info(f"Migrazione {version} applicata con successo")
                    return True
                    
                except Exception as e:
                    # Rollback in caso di errore
                    conn.execute("ROLLBACK")
                    logger.error(f"Errore durante l'applicazione della migrazione {version}: {str(e)}")
                    return False
                
        except Exception as e:
            logger.error(f"Errore durante l'applicazione della migrazione {version}: {str(e)}")
            return False
    
    async def schedule_regular_backups(self, interval_hours: int = BACKUP_INTERVAL_HOURS):
        """
        Pianifica backup regolari del database.
        
        Args:
            interval_hours: Intervallo tra i backup in ore
        """
        if self._scheduled_backup_task is not None:
            self._scheduled_backup_task.cancel()
        
        async def backup_task():
            while True:
                try:
                    self.create_backup()
                    self.cleanup_old_backups()
                    await asyncio.sleep(interval_hours * 3600)  # Converti ore in secondi
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Errore nel task di backup: {str(e)}")
                    await asyncio.sleep(3600)  # Attendi un'ora prima di riprovare in caso di errore
        
        self._scheduled_backup_task = asyncio.create_task(backup_task())
        logger.info(f"Backup regolari pianificati ogni {interval_hours} ore")
    
    def create_backup(self, custom_name: Optional[str] = None) -> Optional[str]:
        """
        Crea un backup del database.
        
        Args:
            custom_name: Nome personalizzato per il backup (opzionale)
            
        Returns:
            Optional[str]: Percorso del file di backup o None in caso di errore
        """
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            if custom_name:
                backup_filename = f"{custom_name}_{timestamp}.db"
            else:
                backup_filename = f"backup_{timestamp}.db"
            
            backup_path = self.backup_dir / backup_filename
            
            # Assicura che il database sia in uno stato coerente
            with self.get_connection() as conn:
                conn.execute("PRAGMA wal_checkpoint(FULL)")
            
            # Copia il file di database
            shutil.copy2(self.db_path, backup_path)
            
            logger.info(f"Backup creato con successo: {backup_path}")
            return str(backup_path)
            
        except Exception as e:
            logger.error(f"Errore durante la creazione del backup: {str(e)}")
            return None
    
    def restore_from_backup(self, backup_path: str) -> bool:
        """
        Ripristina il database da un backup.
        
        Args:
            backup_path: Percorso del file di backup
            
        Returns:
            bool: True se il ripristino è avvenuto con successo, False altrimenti
        """
        if not os.path.exists(backup_path):
            logger.error(f"File di backup non trovato: {backup_path}")
            return False
        
        try:
            # Crea un backup prima del ripristino per sicurezza
            self.create_backup(custom_name="pre_restore")
            
            # Chiudi tutte le connessioni aperte prima del ripristino
            # In questo contesto non è possibile farlo direttamente
            # Si assume che nessuna connessione sia attiva in questo momento
            
            # Sostituisci il database con il backup
            shutil.copy2(backup_path, self.db_path)
            
            logger.info(f"Database ripristinato con successo dal backup: {backup_path}")
            return True
            
        except Exception as e:
            logger.error(f"Errore durante il ripristino del backup: {str(e)}")
            return False
    
    def cleanup_old_backups(self, retention_days: int = BACKUP_RETENTION_DAYS) -> int:
        """
        Elimina i backup più vecchi del periodo di retention.
        
        Args:
            retention_days: Numero di giorni per cui mantenere i backup
            
        Returns:
            int: Numero di backup eliminati
        """
        try:
            threshold_date = datetime.datetime.now() - datetime.timedelta(days=retention_days)
            deleted_count = 0
            
            for backup_file in self.backup_dir.glob("*.db"):
                # Ottieni la data di modifica del file
                mod_time = datetime.datetime.fromtimestamp(os.path.getmtime(backup_file))
                
                # Elimina se più vecchio del threshold
                if mod_time < threshold_date:
                    os.remove(backup_file)
                    deleted_count += 1
            
            if deleted_count > 0:
                logger.info(f"Eliminati {deleted_count} backup più vecchi di {retention_days} giorni")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Errore durante la pulizia dei vecchi backup: {str(e)}")
            return 0
    
    def list_backups(self) -> List[Dict[str, Any]]:
        """
        Elenca tutti i backup disponibili con metadata.
        
        Returns:
            List[Dict[str, Any]]: Lista di dizionari con informazioni sui backup
        """
        try:
            backups = []
            
            for backup_file in sorted(self.backup_dir.glob("*.db"), key=os.path.getmtime, reverse=True):
                mod_time = datetime.datetime.fromtimestamp(os.path.getmtime(backup_file))
                size_bytes = os.path.getsize(backup_file)
                
                backups.append({
                    "filename": backup_file.name,
                    "path": str(backup_file),
                    "date": mod_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "size_bytes": size_bytes,
                    "size_mb": round(size_bytes / (1024 * 1024), 2)
                })
            
            return backups
            
        except Exception as e:
            logger.error(f"Errore durante il recupero della lista dei backup: {str(e)}")
            return []

    # =========================================================================
    # Metodi per la gestione dell'inventario alimentare
    # =========================================================================
    
    def add_food_item(self, user_id: int, name: str, category: str, quantity: float, 
                     unit: str, expiry_date: Optional[str] = None, 
                     notes: Optional[str] = None) -> Optional[int]:
        """
        Aggiunge un elemento all'inventario alimentare.
        
        Args:
            user_id: ID dell'utente
            name: Nome dell'alimento
            category: Categoria dell'alimento
            quantity: Quantità disponibile
            unit: Unità di misura
            expiry_date: Data di scadenza (opzionale, formato YYYY-MM-DD)
            notes: Note aggiuntive (opzionale)
            
        Returns:
            Optional[int]: ID dell'elemento aggiunto o None in caso di errore
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO food_inventory (
                        user_id, name, category, quantity, unit, expiry_date, notes, 
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (user_id, name, category, quantity, unit, expiry_date, notes)
                )
                conn.commit()
                return cursor.lastrowid
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante l'aggiunta dell'alimento: {str(e)}")
            return None
    
    def update_food_item(self, item_id: int, **kwargs) -> bool:
        """
        Aggiorna un elemento dell'inventario alimentare.
        
        Args:
            item_id: ID dell'elemento da aggiornare
            **kwargs: Coppie chiave-valore con i campi da aggiornare
            
        Returns:
            bool: True se l'aggiornamento è riuscito, False altrimenti
        """
        if not kwargs:
            return True  # Nessun aggiornamento richiesto
        
        try:
            # Prepara le parti della query SQL
            set_clauses = []
            params = []
            
            for key, value in kwargs.items():
                # Verifica che la chiave sia un campo valido
                if key in ["name", "category", "quantity", "unit", "expiry_date", "notes"]:
                    set_clauses.append(f"{key} = ?")
                    params.append(value)
            
            if not set_clauses:
                return True  # Nessun campo valido da aggiornare
            
            # Aggiungi sempre updated_at
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            
            # Aggiungi l'ID per la clausola WHERE
            params.append(item_id)
            
            # Componi la query completa
            query = f"""
                UPDATE food_inventory SET 
                {", ".join(set_clauses)}
                WHERE id = ?
            """
            
            with self.get_connection() as conn:
                conn.execute(query, params)
                conn.commit()
                return True
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante l'aggiornamento dell'alimento: {str(e)}")
            return False
    
    def delete_food_item(self, item_id: int) -> bool:
        """
        Elimina un elemento dall'inventario alimentare.
        
        Args:
            item_id: ID dell'elemento da eliminare
            
        Returns:
            bool: True se l'eliminazione è riuscita, False altrimenti
        """
        try:
            with self.get_connection() as conn:
                conn.execute("DELETE FROM food_inventory WHERE id = ?", (item_id,))
                conn.commit()
                return True
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante l'eliminazione dell'alimento: {str(e)}")
            return False
    
    def get_food_inventory(self, user_id: int, category: Optional[str] = None, 
                          expiring_soon: bool = False, days_threshold: int = 7) -> List[Dict[str, Any]]:
        """
        Ottiene l'inventario alimentare di un utente con possibilità di filtrare.
        
        Args:
            user_id: ID dell'utente
            category: Filtra per categoria (opzionale)
            expiring_soon: Se True, mostra solo alimenti in scadenza
            days_threshold: Soglia di giorni per "in scadenza"
            
        Returns:
            List[Dict[str, Any]]: Lista di elementi dell'inventario
        """
        try:
            query = "SELECT * FROM food_inventory WHERE user_id = ?"
            params = [user_id]
            
            if category:
                query += " AND category = ?"
                params.append(category)
            
            if expiring_soon:
                # Calcola la data limite per "in scadenza"
                threshold_date = (datetime.datetime.now() + 
                                 datetime.timedelta(days=days_threshold)).strftime("%Y-%m-%d")
                query += " AND expiry_date IS NOT NULL AND expiry_date <= ?"
                params.append(threshold_date)
            
            query += " ORDER BY expiry_date ASC NULLS LAST, name ASC"
            
            with self.get_connection() as conn:
                cursor = conn.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante il recupero dell'inventario: {str(e)}")
            return []
    
    def get_food_item(self, item_id: int) -> Optional[Dict[str, Any]]:
        """
        Ottiene i dettagli di un singolo elemento dell'inventario.
        
        Args:
            item_id: ID dell'elemento
            
        Returns:
            Optional[Dict[str, Any]]: Dettagli dell'elemento o None se non trovato
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT * FROM food_inventory WHERE id = ?", (item_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante il recupero dei dettagli dell'alimento: {str(e)}")
            return None

    # =========================================================================
    # Metodi per la gestione dei piani alimentari
    # =========================================================================
    
    def create_meal_plan(self, user_id: int, name: str, start_date: str, 
                        end_date: str, notes: Optional[str] = None) -> Optional[int]:
        """
        Crea un nuovo piano alimentare.
        
        Args:
            user_id: ID dell'utente
            name: Nome del piano alimentare
            start_date: Data di inizio (formato YYYY-MM-DD)
            end_date: Data di fine (formato YYYY-MM-DD)
            notes: Note aggiuntive (opzionale)
            
        Returns:
            Optional[int]: ID del piano creato o None in caso di errore
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO meal_plans (
                        user_id, name, start_date, end_date, notes, 
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (user_id, name, start_date, end_date, notes)
                )
                conn.commit()
                return cursor.lastrowid
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante la creazione del piano alimentare: {str(e)}")
            return None
    
    def add_meal_to_plan(self, plan_id: int, date: str, meal_type: str, 
                        description: str, recipe: Optional[str] = None,
                        nutrition_info: Optional[str] = None) -> Optional[int]:
        """
        Aggiunge un pasto a un piano alimentare.
        
        Args:
            plan_id: ID del piano alimentare
            date: Data del pasto (formato YYYY-MM-DD)
            meal_type: Tipo di pasto (es. colazione, pranzo, cena)
            description: Descrizione del pasto
            recipe: Ricetta (opzionale, può essere JSON)
            nutrition_info: Informazioni nutrizionali (opzionale, può essere JSON)
            
        Returns:
            Optional[int]: ID del pasto aggiunto o None in caso di errore
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO meals (
                        plan_id, date, meal_type, description, recipe, nutrition_info, 
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (plan_id, date, meal_type, description, recipe, nutrition_info)
                )
                conn.commit()
                return cursor.lastrowid
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante l'aggiunta del pasto al piano: {str(e)}")
            return None
    
    def get_meal_plans(self, user_id: int, current_only: bool = False) -> List[Dict[str, Any]]:
        """
        Ottiene i piani alimentari di un utente.
        
        Args:
            user_id: ID dell'utente
            current_only: Se True, mostra solo i piani attuali
            
        Returns:
            List[Dict[str, Any]]: Lista di piani alimentari
        """
        try:
            query = "SELECT * FROM meal_plans WHERE user_id = ?"
            params = [user_id]
            
            if current_only:
                # Ottieni solo piani che includono la data corrente
                today = datetime.date.today().strftime("%Y-%m-%d")
                query += " AND start_date <= ? AND end_date >= ?"
                params.extend([today, today])
            
            query += " ORDER BY start_date DESC"
            
            with self.get_connection() as conn:
                cursor = conn.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante il recupero dei piani alimentari: {str(e)}")
            return []
    
    def get_meals_for_date(self, user_id: int, date: str) -> List[Dict[str, Any]]:
        """
        Ottiene tutti i pasti pianificati per una data specifica.
        
        Args:
            user_id: ID dell'utente
            date: Data richiesta (formato YYYY-MM-DD)
            
        Returns:
            List[Dict[str, Any]]: Lista di pasti
        """
        try:
            query = """
                SELECT m.* FROM meals m
                JOIN meal_plans p ON m.plan_id = p.id
                WHERE p.user_id = ? AND m.date = ?
                ORDER BY CASE 
                    WHEN m.meal_type = 'colazione' THEN 1
                    WHEN m.meal_type = 'pranzo' THEN 2
                    WHEN m.meal_type = 'cena' THEN 3
                    ELSE 4
                END
            """
            
            with self.get_connection() as conn:
                cursor = conn.execute(query, (user_id, date))
                return [dict(row) for row in cursor.fetchall()]
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante il recupero dei pasti per la data {date}: {str(e)}")
            return []

    # =========================================================================
    # Metodi per la gestione delle liste della spesa
    # =========================================================================
    
    def create_shopping_list(self, user_id: int, name: str, 
                           notes: Optional[str] = None) -> Optional[int]:
        """
        Crea una nuova lista della spesa.
        
        Args:
            user_id: ID dell'utente
            name: Nome della lista
            notes: Note aggiuntive (opzionale)
            
        Returns:
            Optional[int]: ID della lista creata o None in caso di errore
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO shopping_lists (
                        user_id, name, notes, created_at, updated_at
                    ) VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (user_id, name, notes)
                )
                conn.commit()
                return cursor.lastrowid
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante la creazione della lista della spesa: {str(e)}")
            return None
    
    def add_shopping_item(self, list_id: int, name: str, quantity: Optional[float] = None,
                         unit: Optional[str] = None, category: Optional[str] = None,
                         completed: bool = False, notes: Optional[str] = None) -> Optional[int]:
        """
        Aggiunge un elemento alla lista della spesa.
        
        Args:
            list_id: ID della lista della spesa
            name: Nome dell'articolo
            quantity: Quantità richiesta (opzionale)
            unit: Unità di misura (opzionale)
            category: Categoria dell'articolo (opzionale)
            completed: Stato di completamento
            notes: Note aggiuntive (opzionale)
            
        Returns:
            Optional[int]: ID dell'elemento aggiunto o None in caso di errore
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO shopping_items (
                        list_id, name, quantity, unit, category, completed, notes, 
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (list_id, name, quantity, unit, category, completed, notes)
                )
                conn.commit()
                return cursor.lastrowid
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante l'aggiunta dell'articolo alla lista della spesa: {str(e)}")
            return None
    
    def update_shopping_item(self, item_id: int, **kwargs) -> bool:
        """
        Aggiorna un elemento della lista della spesa.
        
        Args:
            item_id: ID dell'elemento da aggiornare
            **kwargs: Coppie chiave-valore con i campi da aggiornare
            
        Returns:
            bool: True se l'aggiornamento è riuscito, False altrimenti
        """
        if not kwargs:
            return True  # Nessun aggiornamento richiesto
        
        try:
            # Prepara le parti della query SQL
            set_clauses = []
            params = []
            
            for key, value in kwargs.items():
                # Verifica che la chiave sia un campo valido
                if key in ["name", "quantity", "unit", "category", "completed", "notes"]:
                    set_clauses.append(f"{key} = ?")
                    params.append(value)
            
            if not set_clauses:
                return True  # Nessun campo valido da aggiornare
            
            # Aggiungi sempre updated_at
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            
            # Aggiungi l'ID per la clausola WHERE
            params.append(item_id)
            
            # Componi la query completa
            query = f"""
                UPDATE shopping_items SET 
                {", ".join(set_clauses)}
                WHERE id = ?
            """
            
            with self.get_connection() as conn:
                conn.execute(query, params)
                conn.commit()
                return True
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante l'aggiornamento dell'articolo: {str(e)}")
            return False
    
    def mark_shopping_item_as_completed(self, item_id: int, completed: bool = True) -> bool:
        """
        Marca un elemento della lista della spesa come completato o non completato.
        
        Args:
            item_id: ID dell'elemento
            completed: Nuovo stato di completamento
            
        Returns:
            bool: True se l'aggiornamento è riuscito, False altrimenti
        """
        return self.update_shopping_item(item_id, completed=completed)
    
    def get_shopping_lists(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Ottiene tutte le liste della spesa di un utente.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            List[Dict[str, Any]]: Lista delle liste della spesa
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT * FROM shopping_lists 
                    WHERE user_id = ? 
                    ORDER BY created_at DESC
                    """,
                    (user_id,)
                )
                return [dict(row) for row in cursor.fetchall()]
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante il recupero delle liste della spesa: {str(e)}")
            return []
    
    def get_shopping_list_items(self, list_id: int, include_completed: bool = False) -> List[Dict[str, Any]]:
        """
        Ottiene tutti gli elementi di una lista della spesa.
        
        Args:
            list_id: ID della lista della spesa
            include_completed: Se True, include anche gli elementi completati
            
        Returns:
            List[Dict[str, Any]]: Lista degli elementi
        """
        try:
            query = "SELECT * FROM shopping_items WHERE list_id = ?"
            params = [list_id]
            
            if not include_completed:
                query += " AND completed = 0"
            
            query += " ORDER BY category, name"
            
            with self.get_connection() as conn:
                cursor = conn.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante il recupero degli elementi della lista della spesa: {str(e)}")
            return []
    
    def generate_shopping_list_from_inventory(self, user_id: int, threshold: float = 0.2) -> Optional[int]:
        """
        Genera una lista della spesa basata sull'inventario alimentare.
        Aggiunge alla lista gli elementi con quantità inferiore alla soglia.
        
        Args:
            user_id: ID dell'utente
            threshold: Soglia percentuale per considerare l'elemento in esaurimento
            
        Returns:
            Optional[int]: ID della lista della spesa generata o None in caso di errore
        """
        try:
            # Crea una nuova lista della spesa
            list_id = self.create_shopping_list(
                user_id=user_id, 
                name=f"Lista generata {datetime.date.today().strftime('%d/%m/%Y')}",
                notes="Generata automaticamente dall'inventario"
            )
            
            if not list_id:
                return None
            
            # Trova gli alimenti in esaurimento nell'inventario
            # Nota: questo è semplificato, in un sistema reale dovremmo
            # considerare la quantità tipica di ogni alimento
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT * FROM food_inventory 
                    WHERE user_id = ? AND quantity <= ?
                    """,
                    (user_id, threshold)
                )
                
                low_items = cursor.fetchall()
                
                # Aggiungi ogni elemento alla lista della spesa
                for item in low_items:
                    self.add_shopping_item(
                        list_id=list_id,
                        name=item['name'],
                        category=item['category'],
                        unit=item['unit'],
                        notes=f"Inventario in esaurimento ({item['quantity']} {item['unit']})"
                    )
            
            return list_id
            
        except sqlite3.Error as e:
            logger.error(f"Errore durante la generazione della lista della spesa dall'inventario: {str(e)}")
            return None

    # =========================================================================
    # Metodi per la gestione dei dati sanitari
    # =========================================================================
    
    def add_health_condition(self, user_id: int, name: str, description: Optional[str] = None,
                           notes: Optional[str] = None, severity: Optional[str] = None,
                           diagnosed_date: Optional[str] = None) -> Optional[int]:
        """
        Aggiunge una condizione medica per un utente.
        
        Args:
            user_id: ID dell'utente
            name: Nome della condizione
            description: Descrizione della condizione (opzionale)
            notes: Note aggiuntive (opzionale)
            severity: Gravità della condizione (opzionale)
            diagnosed_date: Data della diagnosi (formato YYYY-MM-DD, opzionale)
            
        Returns:
            Optional[int]: ID della condizione aggiunta o None in caso di errore
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO health_conditions (
                        user_id, name, description, notes, severity, diagnosed_date, 
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (user_id, name, description, notes, severity, diagnosed_date)
                )
                conn.commit()
                return cursor.lastrowid
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante l'aggiunta della condizione medica: {str(e)}")
            return None
    
    def add_dietary_restriction(self, user_id: int, name: str, food_type: str,
                              reason: Optional[str] = None, severity: Optional[str] = None,
                              notes: Optional[str] = None) -> Optional[int]:
        """
        Aggiunge una restrizione alimentare per un utente.
        
        Args:
            user_id: ID dell'utente
            name: Nome della restrizione
            food_type: Tipo di alimento da evitare
            reason: Motivo della restrizione (opzionale)
            severity: Gravità della restrizione (opzionale)
            notes: Note aggiuntive (opzionale)
            
        Returns:
            Optional[int]: ID della restrizione aggiunta o None in caso di errore
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO dietary_restrictions (
                        user_id, name, food_type, reason, severity, notes, 
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (user_id, name, food_type, reason, severity, notes)
                )
                conn.commit()
                return cursor.lastrowid
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante l'aggiunta della restrizione alimentare: {str(e)}")
            return None
    
    def add_supplement(self, user_id: int, name: str, dosage: str, 
                      frequency: str, purpose: Optional[str] = None,
                      start_date: Optional[str] = None, end_date: Optional[str] = None,
                      notes: Optional[str] = None) -> Optional[int]:
        """
        Aggiunge un integratore per un utente.
        
        Args:
            user_id: ID dell'utente
            name: Nome dell'integratore
            dosage: Dosaggio
            frequency: Frequenza di assunzione
            purpose: Scopo dell'integratore (opzionale)
            start_date: Data di inizio (formato YYYY-MM-DD, opzionale)
            end_date: Data di fine (formato YYYY-MM-DD, opzionale)
            notes: Note aggiuntive (opzionale)
            
        Returns:
            Optional[int]: ID dell'integratore aggiunto o None in caso di errore
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO supplements (
                        user_id, name, dosage, frequency, purpose, 
                        start_date, end_date, notes, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (user_id, name, dosage, frequency, purpose, start_date, end_date, notes)
                )
                conn.commit()
                return cursor.lastrowid
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante l'aggiunta dell'integratore: {str(e)}")
            return None
    
    def add_health_report(self, user_id: int, report_type: str, date: str,
                        summary: str, details: Optional[str] = None,
                        file_path: Optional[str] = None) -> Optional[int]:
        """
        Aggiunge un referto medico per un utente.
        
        Args:
            user_id: ID dell'utente
            report_type: Tipo di referto
            date: Data del referto (formato YYYY-MM-DD)
            summary: Sintesi del referto
            details: Dettagli completi (opzionale)
            file_path: Percorso a un file allegato (opzionale)
            
        Returns:
            Optional[int]: ID del referto aggiunto o None in caso di errore
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO health_reports (
                        user_id, report_type, date, summary, details, file_path, 
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (user_id, report_type, date, summary, details, file_path)
                )
                conn.commit()
                return cursor.lastrowid
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante l'aggiunta del referto medico: {str(e)}")
            return None
    
    def get_health_conditions(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Ottiene tutte le condizioni mediche di un utente.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            List[Dict[str, Any]]: Lista delle condizioni mediche
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT * FROM health_conditions 
                    WHERE user_id = ? 
                    ORDER BY name
                    """,
                    (user_id,)
                )
                return [dict(row) for row in cursor.fetchall()]
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante il recupero delle condizioni mediche: {str(e)}")
            return []
    
    def get_dietary_restrictions(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Ottiene tutte le restrizioni alimentari di un utente.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            List[Dict[str, Any]]: Lista delle restrizioni alimentari
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT * FROM dietary_restrictions 
                    WHERE user_id = ? 
                    ORDER BY severity DESC, name
                    """,
                    (user_id,)
                )
                return [dict(row) for row in cursor.fetchall()]
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante il recupero delle restrizioni alimentari: {str(e)}")
            return []
    
    def get_supplements(self, user_id: int, active_only: bool = True) -> List[Dict[str, Any]]:
        """
        Ottiene tutti gli integratori di un utente.
        
        Args:
            user_id: ID dell'utente
            active_only: Se True, mostra solo gli integratori attualmente in uso
            
        Returns:
            List[Dict[str, Any]]: Lista degli integratori
        """
        try:
            query = "SELECT * FROM supplements WHERE user_id = ?"
            params = [user_id]
            
            if active_only:
                today = datetime.date.today().strftime("%Y-%m-%d")
                query += " AND (end_date IS NULL OR end_date >= ?)"
                params.append(today)
            
            query += " ORDER BY name"
            
            with self.get_connection() as conn:
                cursor = conn.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante il recupero degli integratori: {str(e)}")
            return []
    
    def get_health_reports(self, user_id: int, report_type: Optional[str] = None,
                         start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Ottiene i referti medici di un utente con possibilità di filtrare.
        
        Args:
            user_id: ID dell'utente
            report_type: Filtra per tipo di referto (opzionale)
            start_date: Data di inizio del periodo (formato YYYY-MM-DD, opzionale)
            end_date: Data di fine del periodo (formato YYYY-MM-DD, opzionale)
            
        Returns:
            List[Dict[str, Any]]: Lista dei referti medici
        """
        try:
            query = "SELECT * FROM health_reports WHERE user_id = ?"
            params = [user_id]
            
            if report_type:
                query += " AND report_type = ?"
                params.append(report_type)
            
            if start_date:
                query += " AND date >= ?"
                params.append(start_date)
            
            if end_date:
                query += " AND date <= ?"
                params.append(end_date)
            
            query += " ORDER BY date DESC"
            
            with self.get_connection() as conn:
                cursor = conn.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante il recupero dei referti medici: {str(e)}")
            return []

    # =========================================================================
    # Metodi per la gestione delle preferenze utente
    # =========================================================================
    
    def set_user_preference(self, user_id: int, key: str, value: str) -> bool:
        """
        Imposta una preferenza utente.
        
        Args:
            user_id: ID dell'utente
            key: Chiave della preferenza
            value: Valore della preferenza
            
        Returns:
            bool: True se l'operazione è riuscita, False altrimenti
        """
        try:
            with self.get_connection() as conn:
                # Verifica se la preferenza esiste già
                cursor = conn.execute(
                    "SELECT id FROM user_preferences WHERE user_id = ? AND key = ?",
                    (user_id, key)
                )
                existing = cursor.fetchone()
                
                if existing:
                    # Aggiorna la preferenza esistente
                    conn.execute(
                        """
                        UPDATE user_preferences 
                        SET value = ?, updated_at = CURRENT_TIMESTAMP 
                        WHERE id = ?
                        """,
                        (value, existing['id'])
                    )
                else:
                    # Inserisci una nuova preferenza
                    conn.execute(
                        """
                        INSERT INTO user_preferences (
                            user_id, key, value, created_at, updated_at
                        ) VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """,
                        (user_id, key, value)
                    )
                
                conn.commit()
                return True
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante l'impostazione della preferenza utente: {str(e)}")
            return False
    
    def get_user_preference(self, user_id: int, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Ottiene una preferenza utente.
        
        Args:
            user_id: ID dell'utente
            key: Chiave della preferenza
            default: Valore predefinito se la preferenza non esiste
            
        Returns:
            Optional[str]: Valore della preferenza o default se non trovata
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT value FROM user_preferences WHERE user_id = ? AND key = ?",
                    (user_id, key)
                )
                row = cursor.fetchone()
                return row['value'] if row else default
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante il recupero della preferenza utente: {str(e)}")
            return default
    
    def get_all_user_preferences(self, user_id: int) -> Dict[str, str]:
        """
        Ottiene tutte le preferenze di un utente.
        
        Args:
            user_id: ID dell'utente
            
        Returns:
            Dict[str, str]: Dizionario delle preferenze chiave-valore
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT key, value FROM user_preferences WHERE user_id = ?",
                    (user_id,)
                )
                return {row['key']: row['value'] for row in cursor.fetchall()}
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante il recupero delle preferenze utente: {str(e)}")
            return {}
    
    # =========================================================================
    # Metodi per l'esportazione e importazione dati
    # =========================================================================
    
    def export_user_data(self, user_id: int, include_health_data: bool = True) -> Optional[Dict[str, Any]]:
        """
        Esporta tutti i dati di un utente in formato JSON.
        
        Args:
            user_id: ID dell'utente
            include_health_data: Se True, include anche i dati sanitari sensibili
            
        Returns:
            Optional[Dict[str, Any]]: Dizionario con tutti i dati dell'utente o None in caso di errore
        """
        try:
            data = {
                "user_id": user_id,
                "export_date": datetime.datetime.now().isoformat(),
                "inventory": self.get_food_inventory(user_id),
                "meal_plans": [],
                "shopping_lists": [],
                "preferences": self.get_all_user_preferences(user_id)
            }
            
            # Ottieni piani alimentari e pasti
            meal_plans = self.get_meal_plans(user_id)
            for plan in meal_plans:
                plan_data = dict(plan)
                
                # Ottieni tutti i pasti associati al piano
                with self.get_connection() as conn:
                    cursor = conn.execute(
                        "SELECT * FROM meals WHERE plan_id = ? ORDER BY date, meal_type",
                        (plan['id'],)
                    )
                    plan_data['meals'] = [dict(row) for row in cursor.fetchall()]
                
                data["meal_plans"].append(plan_data)
            
            # Ottieni liste della spesa e articoli
            shopping_lists = self.get_shopping_lists(user_id)
            for shopping_list in shopping_lists:
                list_data = dict(shopping_list)
                list_data['items'] = self.get_shopping_list_items(shopping_list['id'], include_completed=True)
                data["shopping_lists"].append(list_data)
            
            # Includi dati sanitari se richiesto
            if include_health_data:
                data["health"] = {
                    "conditions": self.get_health_conditions(user_id),
                    "dietary_restrictions": self.get_dietary_restrictions(user_id),
                    "supplements": self.get_supplements(user_id, active_only=False),
                    "reports": self.get_health_reports(user_id)
                }
            
            return data
            
        except Exception as e:
            logger.error(f"Errore durante l'esportazione dei dati utente: {str(e)}")
            return None
    
    def import_user_data(self, data: Dict[str, Any], overwrite: bool = False) -> bool:
        """
        Importa dati utente precedentemente esportati.
        
        Args:
            data: Dizionario con i dati da importare
            overwrite: Se True, sovrascrive i dati esistenti invece di aggiungerli
            
        Returns:
            bool: True se l'importazione è riuscita, False altrimenti
        """
        if not isinstance(data, dict) or "user_id" not in data:
            logger.error("Formato dati non valido per l'importazione")
            return False
        
        user_id = data["user_id"]
        
        try:
            # Inizia una transazione per garantire l'atomicità dell'importazione
            with self.get_connection() as conn:
                conn.execute("BEGIN TRANSACTION")
                
                try:
                    # Se richiesto, elimina i dati esistenti dell'utente
                    if overwrite:
                        tables = [
                            "food_inventory", "meal_plans", "meals", 
                            "shopping_lists", "shopping_items", "user_preferences"
                        ]
                        
                        # Aggiungi tabelle sanitarie se presenti nei dati
                        if "health" in data:
                            tables.extend([
                                "health_conditions", "dietary_restrictions", 
                                "supplements", "health_reports"
                            ])
                        
                        # Elimina i dati esistenti
                        for table in tables:
                            conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
                    
                    # Importa inventario alimentare
                    if "inventory" in data and isinstance(data["inventory"], list):
                        for item in data["inventory"]:
                            # Ignora l'ID originale e lascia che il DB ne assegni uno nuovo
                            self.add_food_item(
                                user_id=user_id,
                                name=item.get("name", ""),
                                category=item.get("category", ""),
                                quantity=item.get("quantity", 0),
                                unit=item.get("unit", ""),
                                expiry_date=item.get("expiry_date"),
                                notes=item.get("notes")
                            )
                    
                    # Importa piani alimentari e pasti
                    if "meal_plans" in data and isinstance(data["meal_plans"], list):
                        for plan_data in data["meal_plans"]:
                            # Crea il piano
                            plan_id = self.create_meal_plan(
                                user_id=user_id,
                                name=plan_data.get("name", ""),
                                start_date=plan_data.get("start_date", ""),
                                end_date=plan_data.get("end_date", ""),
                                notes=plan_data.get("notes")
                            )
                            
                            # Importa i pasti associati
                            if plan_id and "meals" in plan_data and isinstance(plan_data["meals"], list):
                                for meal in plan_data["meals"]:
                                    self.add_meal_to_plan(
                                        plan_id=plan_id,
                                        date=meal.get("date", ""),
                                        meal_type=meal.get("meal_type", ""),
                                        description=meal.get("description", ""),
                                        recipe=meal.get("recipe"),
                                        nutrition_info=meal.get("nutrition_info")
                                    )
                    
                    # Importa liste della spesa e articoli
                    if "shopping_lists" in data and isinstance(data["shopping_lists"], list):
                        for list_data in data["shopping_lists"]:
                            # Crea la lista
                            list_id = self.create_shopping_list(
                                user_id=user_id,
                                name=list_data.get("name", ""),
                                notes=list_data.get("notes")
                            )
                            
                            # Importa gli articoli della lista
                            if list_id and "items" in list_data and isinstance(list_data["items"], list):
                                for item in list_data["items"]:
                                    self.add_shopping_item(
                                        list_id=list_id,
                                        name=item.get("name", ""),
                                        quantity=item.get("quantity"),
                                        unit=item.get("unit"),
                                        category=item.get("category"),
                                        completed=item.get("completed", False),
                                        notes=item.get("notes")
                                    )
                    
                    # Importa preferenze utente
                    if "preferences" in data and isinstance(data["preferences"], dict):
                        for key, value in data["preferences"].items():
                            self.set_user_preference(user_id, key, value)
                    
                    # Importa dati sanitari se presenti
                    if "health" in data and isinstance(data["health"], dict):
                        # Importa condizioni mediche
                        if "conditions" in data["health"] and isinstance(data["health"]["conditions"], list):
                            for condition in data["health"]["conditions"]:
                                self.add_health_condition(
                                    user_id=user_id,
                                    name=condition.get("name", ""),
                                    description=condition.get("description"),
                                    notes=condition.get("notes"),
                                    severity=condition.get("severity"),
                                    diagnosed_date=condition.get("diagnosed_date")
                                )
                        
                        # Importa restrizioni alimentari
                        if "dietary_restrictions" in data["health"] and isinstance(data["health"]["dietary_restrictions"], list):
                            for restriction in data["health"]["dietary_restrictions"]:
                                self.add_dietary_restriction(
                                    user_id=user_id,
                                    name=restriction.get("name", ""),
                                    food_type=restriction.get("food_type", ""),
                                    reason=restriction.get("reason"),
                                    severity=restriction.get("severity"),
                                    notes=restriction.get("notes")
                                )
                        
                        # Importa integratori
                        if "supplements" in data["health"] and isinstance(data["health"]["supplements"], list):
                            for supplement in data["health"]["supplements"]:
                                self.add_supplement(
                                    user_id=user_id,
                                    name=supplement.get("name", ""),
                                    dosage=supplement.get("dosage", ""),
                                    frequency=supplement.get("frequency", ""),
                                    purpose=supplement.get("purpose"),
                                    start_date=supplement.get("start_date"),
                                    end_date=supplement.get("end_date"),
                                    notes=supplement.get("notes")
                                )
                        
                        # Importa referti medici
                        if "reports" in data["health"] and isinstance(data["health"]["reports"], list):
                            for report in data["health"]["reports"]:
                                self.add_health_report(
                                    user_id=user_id,
                                    report_type=report.get("report_type", ""),
                                    date=report.get("date", ""),
                                    summary=report.get("summary", ""),
                                    details=report.get("details"),
                                    file_path=report.get("file_path")
                                )
                    
                    # Commit della transazione
                    conn.commit()
                    logger.info(f"Importazione dati utente completata con successo per l'utente {user_id}")
                    return True
                    
                except Exception as e:
                    # Rollback in caso di errore
                    conn.execute("ROLLBACK")
                    logger.error(f"Errore durante l'importazione dei dati utente: {str(e)}")
                    return False
            
        except Exception as e:
            logger.error(f"Errore durante l'importazione dei dati utente: {str(e)}")
            return False
    
    # =========================================================================
    # Metodi di utilità
    # =========================================================================
    
    def get_database_stats(self) -> Dict[str, Any]:
        """
        Ottiene statistiche generali sul database.
        
        Returns:
            Dict[str, Any]: Dizionario con statistiche del database
        """
        try:
            stats = {
                "db_size_bytes": os.path.getsize(self.db_path),
                "tables": {},
                "last_backup": None,
                "total_backups": 0
            }
            
            # Converti dimensione in MB
            stats["db_size_mb"] = round(stats["db_size_bytes"] / (1024 * 1024), 2)
            
            # Ottieni statistiche per ogni tabella
            with self.get_connection() as conn:
                # Ottieni l'elenco delle tabelle
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                tables = [row['name'] for row in cursor.fetchall()]
                
                # Per ogni tabella, ottieni il conteggio delle righe
                for table in tables:
                    cursor = conn.execute(f"SELECT COUNT(*) as count FROM {table}")
                    row = cursor.fetchone()
                    stats["tables"][table] = row['count']
            
            # Ottieni informazioni sui backup
            backup_files = list(self.backup_dir.glob("*.db"))
            stats["total_backups"] = len(backup_files)
            
            if backup_files:
                # Trova il backup più recente
                latest_backup = max(backup_files, key=os.path.getmtime)
                mod_time = datetime.datetime.fromtimestamp(os.path.getmtime(latest_backup))
                
                stats["last_backup"] = {
                    "filename": latest_backup.name,
                    "date": mod_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "size_bytes": os.path.getsize(latest_backup),
                    "size_mb": round(os.path.getsize(latest_backup) / (1024 * 1024), 2)
                }
            
            return stats
            
        except Exception as e:
            logger.error(f"Errore durante il recupero delle statistiche del database: {str(e)}")
            return {"error": str(e)}
    
    def execute_custom_query(self, query: str, params: Optional[Tuple] = None, 
                            fetch_all: bool = True) -> Optional[List[Dict[str, Any]]]:
        """
        Esegue una query SQL personalizzata.
        ATTENZIONE: Usare con cautela, solo per scopi amministrativi.
        
        Args:
            query: Query SQL da eseguire
            params: Parametri per la query (opzionale)
            fetch_all: Se True, restituisce tutte le righe, altrimenti solo la prima
            
        Returns:
            Optional[List[Dict[str, Any]]]: Risultati della query o None in caso di errore
        """
        try:
            params = params or ()
            
            with self.get_connection() as conn:
                cursor = conn.execute(query, params)
                
                if fetch_all:
                    return [dict(row) for row in cursor.fetchall()]
                else:
                    row = cursor.fetchone()
                    return [dict(row)] if row else []
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante l'esecuzione della query personalizzata: {str(e)}")
            return None
    
    def vacuum_database(self) -> bool:
        """
        Esegue una pulizia e ottimizzazione del database (VACUUM).
        
        Returns:
            bool: True se l'operazione è riuscita, False altrimenti
        """
        try:
            # Prima crea un backup
            self.create_backup(custom_name="pre_vacuum")
            
            with self.get_connection() as conn:
                conn.execute("VACUUM")
                return True
                
        except sqlite3.Error as e:
            logger.error(f"Errore durante l'ottimizzazione del database: {str(e)}")
            return False


# Funzioni di utilità

def test_database_connection(db_path: str) -> bool:
    """
    Testa la connessione al database.
    
    Args:
        db_path: Percorso del file database
        
    Returns:
        bool: True se la connessione è riuscita, False altrimenti
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.close()
        return True
    except sqlite3.Error:
        return False


if __name__ == "__main__":
    """Test di base del modulo."""
    
    async def run_test():
        try:
            print("Inizializzazione del DataManager...")
            dm = DataManager()
            
            print("Test di inizializzazione del database...")
            if dm.initialize_database():
                print("✅ Database inizializzato con successo!")
                
                # Test creazione di un backup
                backup_path = dm.create_backup()
                if backup_path:
                    print(f"✅ Backup creato: {backup_path}")
                else:
                    print("❌ Errore nella creazione del backup")
                
                # Test statistiche database
                stats = dm.get_database_stats()
                print("\nStatistiche del database:")
                print(f"- Dimensione: {stats['db_size_mb']} MB")
                print(f"- Tabelle: {len(stats['tables'])}")
                for table, count in stats['tables'].items():
                    print(f"  - {table}: {count} righe")
                
                # Avvio backup regolari per test
                print("\nPianificazione backup regolari (1 ora)...")
                await dm.schedule_regular_backups(interval_hours=1)
                print("✅ Backup pianificati")
                
                # Attesa breve per test
                print("\nAttesa di 3 secondi per il task di backup...")
                await asyncio.sleep(3)
                print("Test completato!")
                
            else:
                print("❌ Errore nell'inizializzazione del database")
                
        except Exception as e:
            print(f"❌ Errore durante il test: {str(e)}")
    
    # Esegui il test asincrono
    asyncio.run(run_test())