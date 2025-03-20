#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plugin_manager.py - Gestore dei plugin per l'assistente personale

Questo modulo gestisce il caricamento, l'attivazione e l'interazione con i plugin.
Fornisce un'interfaccia strutturata per estendere le funzionalità dell'assistente
tramite plugin modulari, incluso il supporto per ricerche su internet con DuckDuckGo.
"""

import os
import sys
import importlib
import logging
import inspect
import pkgutil
import json
from typing import Dict, List, Optional, Union, Any, Callable, Type
from pathlib import Path
import subprocess
import tempfile
import shutil

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Costanti
PLUGINS_DIR = "plugins"
DEFAULT_PLUGINS = ["duckduckgo_search"]
PLUGIN_CONFIG_FILE = "plugin_config.json"


class PluginException(Exception):
    """Eccezione personalizzata per errori relativi ai plugin."""
    pass


class BasePlugin:
    """
    Classe base per tutti i plugin.
    Definisce l'interfaccia standard che ogni plugin deve implementare.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Inizializza il plugin con la configurazione fornita.
        
        Args:
            config: Configurazione specifica del plugin (opzionale)
        """
        self.config = config or {}
        self.name = self.__class__.__name__
        self.version = "1.0.0"
        self.description = "Plugin base"
        self.enabled = True
        
    def initialize(self) -> bool:
        """
        Inizializza il plugin e verifica che sia pronto per l'uso.
        
        Returns:
            bool: True se l'inizializzazione è riuscita, False altrimenti
        """
        return True
    
    def shutdown(self) -> bool:
        """
        Esegue le operazioni di pulizia prima della disattivazione del plugin.
        
        Returns:
            bool: True se la disattivazione è riuscita, False altrimenti
        """
        return True
    
    def get_capabilities(self) -> List[str]:
        """
        Restituisce l'elenco delle funzionalità fornite dal plugin.
        
        Returns:
            List[str]: Elenco delle funzionalità
        """
        return []
    
    def execute(self, action: str, params: Dict[str, Any] = None) -> Any:
        """
        Esegue un'azione specifica con i parametri forniti.
        
        Args:
            action: Nome dell'azione da eseguire
            params: Parametri per l'azione (opzionale)
            
        Returns:
            Any: Risultato dell'azione
            
        Raises:
            PluginException: Se l'azione non è supportata o si verifica un errore
        """
        raise PluginException(f"Azione '{action}' non supportata dal plugin {self.name}")
    
    def get_info(self) -> Dict[str, Any]:
        """
        Restituisce informazioni sul plugin.
        
        Returns:
            Dict[str, Any]: Informazioni sul plugin
        """
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "enabled": self.enabled,
            "capabilities": self.get_capabilities()
        }


class DuckDuckGoSearchPlugin(BasePlugin):
    """
    Plugin per l'integrazione con DuckDuckGo Search.
    Permette di eseguire ricerche su internet tramite il motore DuckDuckGo.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Inizializza il plugin DuckDuckGo Search.
        
        Args:
            config: Configurazione specifica del plugin (opzionale)
        """
        super().__init__(config)
        self.name = "DuckDuckGoSearch"
        self.version = "1.0.0"
        self.description = "Plugin per la ricerca su internet tramite DuckDuckGo"
        
        # Impostazioni predefinite
        self.default_config = {
            "max_results": 5,
            "region": "wt-wt",  # Worldwide
            "safesearch": "moderate",
            "timelimit": None,  # No time limit
            "backend": "api"    # Use API instead of HTML
        }
        
        # Unisci la configurazione predefinita con quella fornita
        self.config = {**self.default_config, **(config or {})}
        
        # Flag per indicare se il pacchetto duckduckgo_search è installato
        self.is_available = False
        
    def initialize(self) -> bool:
        """
        Inizializza il plugin e verifica che il pacchetto duckduckgo_search sia installato.
        
        Returns:
            bool: True se l'inizializzazione è riuscita, False altrimenti
        """
        try:
            import duckduckgo_search
            self.is_available = True
            logger.info(f"Plugin {self.name} inizializzato correttamente.")
            return True
        except ImportError:
            logger.warning(f"Il pacchetto 'duckduckgo_search' non è installato. Il plugin {self.name} non sarà disponibile.")
            self.is_available = False
            return False
    
    def get_capabilities(self) -> List[str]:
        """
        Restituisce l'elenco delle funzionalità fornite dal plugin.
        
        Returns:
            List[str]: Elenco delle funzionalità
        """
        return [
            "text_search",
            "image_search",
            "news_search",
            "video_search",
            "answers",
            "suggestions"
        ]
    
    def execute(self, action: str, params: Dict[str, Any] = None) -> Any:
        """
        Esegue una ricerca su DuckDuckGo in base all'azione specificata.
        
        Args:
            action: Tipo di ricerca ('text_search', 'image_search', ecc.)
            params: Parametri per la ricerca (opzionale)
            
        Returns:
            Any: Risultati della ricerca
            
        Raises:
            PluginException: Se il plugin non è disponibile o si verifica un errore
        """
        if not self.is_available:
            raise PluginException("Il plugin DuckDuckGoSearch non è disponibile. Installa il pacchetto 'duckduckgo_search'.")
        
        params = params or {}
        
        try:
            from duckduckgo_search import DDGS
            
            # Crea un'istanza di DDGS
            ddgs = DDGS()
            
            # Parametri comuni
            query = params.get("query", "")
            if not query:
                raise PluginException("La query di ricerca è obbligatoria.")
            
            max_results = params.get("max_results", self.config["max_results"])
            region = params.get("region", self.config["region"])
            safesearch = params.get("safesearch", self.config["safesearch"])
            timelimit = params.get("timelimit", self.config["timelimit"])
            
            # Esegui l'azione richiesta
            if action == "text_search":
                results = list(ddgs.text(
                    query,
                    region=region,
                    safesearch=safesearch,
                    timelimit=timelimit,
                    max_results=max_results
                ))
                return results
                
            elif action == "image_search":
                image_type = params.get("image_type", "photo")
                size = params.get("size", None)
                color = params.get("color", None)
                layout = params.get("layout", None)
                license_type = params.get("license", None)
                
                results = list(ddgs.images(
                    query,
                    region=region,
                    safesearch=safesearch,
                    size=size,
                    color=color,
                    type_image=image_type,
                    layout=layout,
                    license_image=license_type,
                    max_results=max_results
                ))
                return results
                
            elif action == "news_search":
                results = list(ddgs.news(
                    query,
                    region=region,
                    safesearch=safesearch,
                    timelimit=timelimit,
                    max_results=max_results
                ))
                return results
                
            elif action == "video_search":
                results = list(ddgs.videos(
                    query,
                    region=region,
                    safesearch=safesearch,
                    timelimit=timelimit,
                    max_results=max_results
                ))
                return results
                
            elif action == "answers":
                return ddgs.answers(query)
                
            elif action == "suggestions":
                return ddgs.suggestions(query)
                
            else:
                raise PluginException(f"Azione '{action}' non supportata.")
                
        except Exception as e:
            logger.error(f"Errore durante l'esecuzione dell'azione '{action}': {str(e)}")
            raise PluginException(f"Errore durante l'esecuzione dell'azione '{action}': {str(e)}")
    
    def search_cli(self, command: str) -> str:
        """
        Esegue una ricerca tramite la CLI di duckduckgo_search.
        
        Args:
            command: Comando da eseguire (es. "ddgs text -k 'query'")
            
        Returns:
            str: Output del comando
            
        Raises:
            PluginException: Se si verifica un errore durante l'esecuzione del comando
        """
        try:
            # Verifica che il comando inizi con "ddgs"
            if not command.startswith("ddgs "):
                command = "ddgs " + command
            
            # Esegui il comando
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                raise PluginException(f"Errore durante l'esecuzione del comando: {result.stderr}")
            
            return result.stdout
            
        except Exception as e:
            logger.error(f"Errore durante l'esecuzione del comando CLI: {str(e)}")
            raise PluginException(f"Errore durante l'esecuzione del comando CLI: {str(e)}")


class PluginManager:
    """
    Classe principale per la gestione dei plugin.
    Si occupa di caricare, attivare e disattivare i plugin,
    oltre a fornire un'interfaccia per l'interazione con essi.
    
    Supporta sia i plugin tradizionali che i tool per l'API di Claude,
    permettendo di utilizzare function calling attraverso Tool Use.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Inizializza il gestore dei plugin.
        
        Args:
            config: Configurazione per il gestore dei plugin (opzionale)
        """
        self.config = config or {}
        self.plugins_dir = self.config.get("plugins_dir", PLUGINS_DIR)
        self.enabled_plugins = self.config.get("plugins", DEFAULT_PLUGINS)
        
        # Dizionario per memorizzare le istanze dei plugin
        self.plugins = {}
        
        # Dizionario per memorizzare le classi dei plugin
        self.plugin_classes = {}
        
        # Dizionario per memorizzare i tool di Claude
        self.claude_tools = {}
        
        # Configurazione per Tool Use di Claude
        self.tool_use_config = {
            "disable_parallel_tool_use": self.config.get("disable_parallel_tool_use", False),
            "tool_choice": self.config.get("tool_choice", "auto")
        }
        
        # Carica i plugin integrati
        self._load_builtin_plugins()
        
        # Carica i plugin dal file system
        self._load_external_plugins()
        
        # Inizializza i plugin abilitati
        self._initialize_enabled_plugins()
        
        logger.info(f"PluginManager inizializzato con {len(self.plugins)} plugin.")
    
    def _load_builtin_plugins(self):
        """
        Carica i plugin integrati direttamente nel codice.
        """
        # Registra il plugin DuckDuckGo Search
        self.plugin_classes["duckduckgo_search"] = DuckDuckGoSearchPlugin
        
        logger.info(f"Caricati {len(self.plugin_classes)} plugin integrati.")
    
    def _load_external_plugins(self):
        """
        Carica i plugin esterni dal file system.
        """
        plugins_path = Path(self.plugins_dir)
        
        # Controlla se la directory dei plugin esiste
        if not plugins_path.exists() or not plugins_path.is_dir():
            logger.warning(f"La directory dei plugin '{self.plugins_dir}' non esiste.")
            return
        
        # Aggiungi la directory dei plugin al path di Python
        sys.path.insert(0, str(plugins_path))
        
        # Cerca i moduli nella directory dei plugin
        for finder, name, ispkg in pkgutil.iter_modules([str(plugins_path)]):
            try:
                # Importa il modulo
                module = importlib.import_module(name)
                
                # Cerca le classi che ereditano da BasePlugin
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    
                    if (inspect.isclass(attr) and 
                        issubclass(attr, BasePlugin) and 
                        attr is not BasePlugin):
                        
                        # Registra la classe del plugin
                        self.plugin_classes[name] = attr
                        logger.info(f"Plugin esterno '{name}' caricato: {attr.__name__}")
            
            except Exception as e:
                logger.error(f"Errore durante il caricamento del plugin '{name}': {str(e)}")
        
        # Rimuovi la directory dei plugin dal path di Python
        sys.path.pop(0)
    
    def _initialize_enabled_plugins(self):
        """
        Inizializza tutti i plugin abilitati.
        """
        for plugin_name in self.enabled_plugins:
            self.activate_plugin(plugin_name)
    
    def activate_plugin(self, plugin_name: str, config: Dict[str, Any] = None) -> bool:
        """
        Attiva un plugin specifico.
        
        Args:
            plugin_name: Nome del plugin da attivare
            config: Configurazione specifica per il plugin (opzionale)
            
        Returns:
            bool: True se l'attivazione è riuscita, False altrimenti
        """
        # Controlla se il plugin è già attivo
        if plugin_name in self.plugins:
            logger.info(f"Il plugin '{plugin_name}' è già attivo.")
            return True
        
        # Controlla se la classe del plugin è stata caricata
        if plugin_name not in self.plugin_classes:
            logger.warning(f"Il plugin '{plugin_name}' non è stato trovato.")
            return False
        
        try:
            # Crea un'istanza del plugin
            plugin_class = self.plugin_classes[plugin_name]
            plugin = plugin_class(config)
            
            # Inizializza il plugin
            success = plugin.initialize()
            
            if success:
                # Registra il plugin
                self.plugins[plugin_name] = plugin
                logger.info(f"Plugin '{plugin_name}' attivato con successo.")
                return True
            else:
                logger.warning(f"Inizializzazione del plugin '{plugin_name}' fallita.")
                return False
                
        except Exception as e:
            logger.error(f"Errore durante l'attivazione del plugin '{plugin_name}': {str(e)}")
            return False
    
    def deactivate_plugin(self, plugin_name: str) -> bool:
        """
        Disattiva un plugin specifico.
        
        Args:
            plugin_name: Nome del plugin da disattivare
            
        Returns:
            bool: True se la disattivazione è riuscita, False altrimenti
        """
        # Controlla se il plugin è attivo
        if plugin_name not in self.plugins:
            logger.warning(f"Il plugin '{plugin_name}' non è attivo.")
            return False
        
        try:
            # Ottieni l'istanza del plugin
            plugin = self.plugins[plugin_name]
            
            # Esegui la procedura di shutdown
            success = plugin.shutdown()
            
            if success:
                # Rimuovi il plugin dalla lista dei plugin attivi
                del self.plugins[plugin_name]
                logger.info(f"Plugin '{plugin_name}' disattivato con successo.")
                return True
            else:
                logger.warning(f"Disattivazione del plugin '{plugin_name}' fallita.")
                return False
                
        except Exception as e:
            logger.error(f"Errore durante la disattivazione del plugin '{plugin_name}': {str(e)}")
            return False
    
    def get_plugin(self, plugin_name: str) -> Optional[BasePlugin]:
        """
        Ottiene un'istanza di un plugin attivo.
        
        Args:
            plugin_name: Nome del plugin
            
        Returns:
            Optional[BasePlugin]: Istanza del plugin o None se non trovato
        """
        return self.plugins.get(plugin_name)
    
    def execute_plugin_action(self, plugin_name: str, action: str, params: Dict[str, Any] = None) -> Any:
        """
        Esegue un'azione su un plugin specifico.
        
        Args:
            plugin_name: Nome del plugin
            action: Nome dell'azione da eseguire
            params: Parametri per l'azione (opzionale)
            
        Returns:
            Any: Risultato dell'azione
            
        Raises:
            PluginException: Se il plugin non è attivo o si verifica un errore
        """
        # Controlla se il plugin è attivo
        if plugin_name not in self.plugins:
            raise PluginException(f"Il plugin '{plugin_name}' non è attivo.")
        
        # Ottieni l'istanza del plugin
        plugin = self.plugins[plugin_name]
        
        # Esegui l'azione
        return plugin.execute(action, params)
    
    def get_active_plugins(self) -> Dict[str, BasePlugin]:
        """
        Ottiene un dizionario di tutti i plugin attivi.
        
        Returns:
            Dict[str, BasePlugin]: Dizionario dei plugin attivi
        """
        return self.plugins.copy()
    
    def get_available_plugins(self) -> List[str]:
        """
        Ottiene l'elenco di tutti i plugin disponibili.
        
        Returns:
            List[str]: Elenco dei nomi dei plugin disponibili
        """
        return list(self.plugin_classes.keys())
    
    def get_plugin_info(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """
        Ottiene informazioni su un plugin specifico.
        
        Args:
            plugin_name: Nome del plugin
            
        Returns:
            Optional[Dict[str, Any]]: Informazioni sul plugin o None se non trovato
        """
        plugin = self.get_plugin(plugin_name)
        return plugin.get_info() if plugin else None
    
    def search_internet(self, query: str, search_type: str = "text_search", max_results: int = 5) -> List[Dict[str, Any]]:
        """
        Funzione di utilità per eseguire una ricerca su internet utilizzando DuckDuckGo.
        
        Args:
            query: Query di ricerca
            search_type: Tipo di ricerca ('text_search', 'image_search', 'news_search', 'video_search')
            max_results: Numero massimo di risultati
            
        Returns:
            List[Dict[str, Any]]: Risultati della ricerca
            
        Raises:
            PluginException: Se si verifica un errore durante la ricerca
        """
        try:
            # Controlla se il plugin DuckDuckGo è attivo
            if "duckduckgo_search" not in self.plugins:
                # Prova ad attivare il plugin
                success = self.activate_plugin("duckduckgo_search")
                if not success:
                    raise PluginException("Il plugin DuckDuckGo Search non è disponibile.")
            
            # Esegui la ricerca
            results = self.execute_plugin_action(
                "duckduckgo_search",
                search_type,
                {
                    "query": query,
                    "max_results": max_results
                }
            )
            
            return results
            
        except Exception as e:
            logger.error(f"Errore durante la ricerca su internet: {str(e)}")
            raise PluginException(f"Errore durante la ricerca su internet: {str(e)}")
    
    def install_plugin(self, plugin_package: str) -> bool:
        """
        Installa un plugin da PyPI.
        
        Args:
            plugin_package: Nome del pacchetto da installare
            
        Returns:
            bool: True se l'installazione è riuscita, False altrimenti
        """
        try:
            # Installa il pacchetto
            subprocess.check_call([sys.executable, "-m", "pip", "install", plugin_package])
            
            logger.info(f"Plugin '{plugin_package}' installato con successo.")
            return True
            
        except Exception as e:
            logger.error(f"Errore durante l'installazione del plugin '{plugin_package}': {str(e)}")
            return False
    
    def save_plugin_configuration(self) -> bool:
        """
        Salva la configurazione dei plugin in un file JSON.
        
        Returns:
            bool: True se il salvataggio è riuscito, False altrimenti
        """
        try:
            # Crea la configurazione da salvare
            config = {
                "enabled_plugins": self.enabled_plugins,
                "plugin_configs": {}
            }
            
            # Aggiungi la configurazione di ogni plugin attivo
            for plugin_name, plugin in self.plugins.items():
                config["plugin_configs"][plugin_name] = plugin.config
            
            # Salva la configurazione in un file JSON
            with open(PLUGIN_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)
            
            logger.info(f"Configurazione dei plugin salvata in '{PLUGIN_CONFIG_FILE}'.")
            return True
            
        except Exception as e:
            logger.error(f"Errore durante il salvataggio della configurazione dei plugin: {str(e)}")
            return False
    
    def load_plugin_configuration(self) -> bool:
        """
        Carica la configurazione dei plugin da un file JSON.
        
        Returns:
            bool: True se il caricamento è riuscito, False altrimenti
        """
        try:
            # Controlla se il file di configurazione esiste
            if not os.path.exists(PLUGIN_CONFIG_FILE):
                logger.warning(f"Il file di configurazione '{PLUGIN_CONFIG_FILE}' non esiste.")
                return False
            
            # Carica la configurazione dal file JSON
            with open(PLUGIN_CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            
            # Aggiorna la lista dei plugin abilitati
            self.enabled_plugins = config.get("enabled_plugins", DEFAULT_PLUGINS)
            
            # Disattiva tutti i plugin attivi
            for plugin_name in list(self.plugins.keys()):
                self.deactivate_plugin(plugin_name)
            
            # Attiva i plugin con la configurazione caricata
            plugin_configs = config.get("plugin_configs", {})
            for plugin_name in self.enabled_plugins:
                plugin_config = plugin_configs.get(plugin_name, {})
                self.activate_plugin(plugin_name, plugin_config)
            
            logger.info(f"Configurazione dei plugin caricata da '{PLUGIN_CONFIG_FILE}'.")
            return True
            
        except Exception as e:
            logger.error(f"Errore durante il caricamento della configurazione dei plugin: {str(e)}")
            return False


# Funzioni di utilità

def get_duckduckgo_search_results(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Funzione di utilità per ottenere risultati di ricerca da DuckDuckGo.
    
    Args:
        query: Query di ricerca
        max_results: Numero massimo di risultati
        
    Returns:
        List[Dict[str, Any]]: Risultati della ricerca
    """
    try:
        # Crea un'istanza temporanea del plugin manager
        plugin_manager = PluginManager()
        
        # Esegui la ricerca
        results = plugin_manager.search_internet(query, "text_search", max_results)
        
        return results
        
    except Exception as e:
        logger.error(f"Errore durante la ricerca su DuckDuckGo: {str(e)}")
        return []


if __name__ == "__main__":
    """Test di base del modulo."""
    
    async def run_test():
        try:
            print("Inizializzazione del PluginManager...")
            plugin_manager = PluginManager()
            
            print("\nPlugin disponibili:")
            available_plugins = plugin_manager.get_available_plugins()
            for plugin_name in available_plugins:
                print(f"- {plugin_name}")
            
            print("\nPlugin attivi:")
            active_plugins = plugin_manager.get_active_plugins()
            for plugin_name, plugin in active_plugins.items():
                info = plugin.get_info()
                print(f"- {info['name']} (v{info['version']}): {info['description']}")
                print(f"  Funzionalità: {', '.join(info['capabilities'])}")
            
            # Test di ricerca con DuckDuckGo
            if "duckduckgo_search" in active_plugins:
                print("\nTest di ricerca con DuckDuckGo...")
                query = "assistente personale AI"
                print(f"Query: '{query}'")
                
                try:
                    results = plugin_manager.search_internet(query, max_results=3)
                    
                    print(f"Risultati trovati: {len(results)}")
                    for i, result in enumerate(results, 1):
                        print(f"\nRisultato {i}:")
                        print(f"- Titolo: {result.get('title', 'N/A')}")
                        print(f"- URL: {result.get('href', 'N/A')}")
                        print(f"- Descrizione: {result.get('body', 'N/A')[:100]}...")
                    
                except PluginException as e:
                    print(f"Errore: {str(e)}")
            
            print("\nTest completato!")
            
        except Exception as e:
            print(f"Errore durante il test: {str(e)}")
    
    # Esegui il test
    import asyncio
    asyncio.run(run_test())
