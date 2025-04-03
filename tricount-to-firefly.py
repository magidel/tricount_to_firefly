import requests
import json
import uuid
import os
import re
import hashlib
import argparse
from datetime import datetime, timedelta
import rsa
import pandas as pd
from tqdm import tqdm

# Configurazione con variabili
DEFAULT_TRICOUNT_KEY = "XXXXXXXXXX"  # Chiave Tricount predefinita
DEFAULT_FIREFLY_HOST = "http://192.168.1.100"    # Host Firefly III predefinita
DEFAULT_FIREFLY_TOKEN = "abcdef123456"          # Token Firefly III predefinito
DEFAULT_ACCOUNT_ID = None                     # Lascia None per trovare il primo account disponibile
DEFAULT_DAYS_RANGE = 730                      # Numero di giorni per il range temporale di caricamento delle transazioni esistenti
HASH_FILE = "hashes.json"	              # File per salvare gli hash

class TricountAPI:
    """Classe per interagire con l'API di Tricount"""
    def __init__(self):
        self.base_url = "https://api.tricount.bunq.com"
        self.app_installation_id = str(uuid.uuid4())
        self.public_key, self.private_key = rsa.newkeys(2048)
        self.rsa_public_key_pem = self.public_key.save_pkcs1(format="PEM").decode()
        self.headers = {
            "User-Agent": "com.bunq.tricount.android:RELEASE:7.0.7:3174:ANDROID:13:C",
            "app-id": self.app_installation_id,
            "X-Bunq-Client-Request-Id": "049bfcdf-6ae4-4cee-af7b-45da31ea85d0"
        }
        self.auth_token = None
        self.user_id = None

    def authenticate(self):
        auth_url = f"{self.base_url}/v1/session-registry-installation"
        auth_payload = {
            "app_installation_uuid": self.app_installation_id,
            "client_public_key": self.rsa_public_key_pem,
            "device_description": "Android"
        }
        response = requests.post(auth_url, json=auth_payload, headers=self.headers)
        response.raise_for_status()
        auth_data = response.json()

        response_items = auth_data["Response"]
        self.auth_token = next(item["Token"]["token"] for item in response_items if "Token" in item)
        self.user_id = next(item["UserPerson"]["id"] for item in response_items if "UserPerson" in item)
        self.headers["X-Bunq-Client-Authentication"] = self.auth_token

    def fetch_tricount_data(self, tricount_key):
        tricount_url = f"{self.base_url}/v1/user/{self.user_id}/registry?public_identifier_token={tricount_key}"
        response = requests.get(tricount_url, headers=self.headers)
        response.raise_for_status()
        return response.json()

class TricountHandler:
    """Gestisce i dati Tricount (parsing, pulizia, esportazione)"""
    @staticmethod
    def get_tricount_title(data):
        return data["Response"][0]["Registry"]["title"]
    
    @staticmethod
    def clean_category(category):
        if not category:
            return ""
        emoji_pattern = re.compile("["
                                   u"\U0001F600-\U0001F64F"
                                   u"\U0001F300-\U0001F5FF"
                                   u"\U0001F680-\U0001F6FF"
                                   u"\U0001F700-\U0001F77F"
                                   u"\U0001F780-\U0001F7FF"
                                   u"\U0001F800-\U0001F8FF"
                                   u"\U0001F900-\U0001F9FF"
                                   u"\U0001FA00-\U0001FA6F"
                                   u"\U0001FA70-\U0001FAFF"
                                   u"\U00002702-\U000027B0"
                                   u"\U000024C2-\U0001F251"
                                   u"\U0000200D"
                                   u"\U0000FE0F"
                                   "]+", flags=re.UNICODE)
        clean_text = emoji_pattern.sub(r'', category).strip()
        return clean_text[0].upper() + clean_text[1:].lower() if clean_text else clean_text

    @staticmethod
    def parse_tricount_data(data):
        registry = data["Response"][0]["Registry"]
        transactions = []
        for entry in registry["all_registry_entry"]:
            transaction = entry["RegistryEntry"]
            type_transaction = transaction["type_transaction"]
            who_paid = transaction["membership_owned"]["RegistryMembershipNonUser"]["alias"]["display_name"]
            total = float(transaction["amount"]["value"]) * -1
            currency = transaction["amount"]["currency"]
            description = transaction.get("description", "")
            when = transaction["date"]
            shares = {
                alloc["membership"]["RegistryMembershipNonUser"]["alias"]["display_name"]: abs(float(alloc["amount"]["value"]))
                for alloc in transaction["allocations"]
            }
            uuid = transaction["uuid"]
            raw_category = transaction["category_custom"] if transaction["category_custom"] is not None else transaction["category"]
            cleaned_category = TricountHandler.clean_category(raw_category)
            
            transactions.append({
                "UUID": uuid,
                "Type": type_transaction,
                "Who Paid": who_paid,
                "Total": total,
                "Currency": currency,
                "Description": description,
                "When": when,
                "Shares": shares,
                "RawCategory": raw_category,
                "Category": cleaned_category
            })
        return transactions

    @staticmethod
    def write_to_excel(transactions, file_name):
        transactions_data = []
        for transaction in transactions:
            involved = ", ".join([name for name, amount in transaction["Shares"].items() if amount > 0])
            row_data = {
                "UUID": transaction["UUID"],
                "Who Paid": transaction["Who Paid"],
                "Total": abs(transaction["Total"]),
                "Currency": transaction["Currency"],
                "Description": transaction["Description"],
                "When": datetime.strptime(transaction["When"], "%Y-%m-%d %H:%M:%S.%f").strftime("%Y-%m-%d"),
                "Involved": involved,
                "Category": transaction["Category"]
            }
            transactions_data.append(row_data)

        df = pd.DataFrame(transactions_data)
        df.to_excel(f"{file_name}.xlsx", index=False)
        print(f"Transazioni salvate in {file_name}.xlsx")
        return df

class FireflyIIIImporter:
    """Classe per importare transazioni in Firefly III"""
    def __init__(self, host, api_token, days_range=DEFAULT_DAYS_RANGE):
        self.host = host.rstrip('/')
        self.api_token = api_token
        self.days_range = days_range
        self.headers = {
            'Authorization': f'Bearer {self.api_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        self.verify_connection()
        
        self.accounts_cache = {}
        self.categories_cache = {}
        self.duplicate_hashes = {}  # Dizionario per salvare UUID e data
        self.transactions_loaded = False
        
        self.default_account_id = DEFAULT_ACCOUNT_ID
        if not self.default_account_id:
            self.find_default_account()
            
        if not self.default_account_id:
            print("Errore: Impossibile trovare un account sorgente valido.")
            exit(1)
            
        self.load_existing_hashes()
        self.load_existing_transactions()

    def verify_connection(self):
        try:
            response = requests.get(f"{self.host}/api/v1/about", headers=self.headers)
            response.raise_for_status()
            print(f"Connessione riuscita a Firefly III v{response.json()['data']['version']}")
        except Exception as e:
            print(f"Impossibile connettersi a Firefly III: {str(e)}")
            exit(1)

    def find_default_account(self):
        try:
            response = requests.get(
                f"{self.host}/api/v1/accounts",
                headers=self.headers,
                params={'type': 'asset'}
            )
            response.raise_for_status()
            accounts = response.json()['data']
            if accounts:
                self.default_account_id = accounts[0]['id']
                print(f"Utilizzo '{accounts[0]['attributes']['name']}' come account sorgente (ID: {self.default_account_id})")
        except Exception as e:
            print(f"Errore nella ricerca dell'account: {str(e)}")

    def load_existing_hashes(self):
        """Carica gli UUID delle transazioni precedenti da file locale"""
        if os.path.exists(HASH_FILE):
            try:
                with open(HASH_FILE, 'r') as f:
                    self.duplicate_hashes = json.load(f)
                print(f"Caricati {len(self.duplicate_hashes)} UUID da {HASH_FILE}")
            except Exception as e:
                print(f"Errore nel caricamento degli UUID da {HASH_FILE}: {str(e)}")
                self.duplicate_hashes = {}

    def save_hashes(self):
        """Salva gli UUID su file locale"""
        try:
            with open(HASH_FILE, 'w') as f:
                json.dump(self.duplicate_hashes, f, indent=2)
            print(f"Salvati {len(self.duplicate_hashes)} UUID in {HASH_FILE}")
        except Exception as e:
            print(f"Errore nel salvataggio degli UUID: {str(e)}")

    def clean_duplicate_hashes(self):
        """Pulisce gli UUID, mantenendo solo quelli degli ultimi days_range giorni"""
        cutoff_date = datetime.now() - timedelta(days=self.days_range)
        original_count = len(self.duplicate_hashes)
        self.duplicate_hashes = {
            uuid_value: date 
            for uuid_value, date in self.duplicate_hashes.items()
            if datetime.strptime(date, "%Y-%m-%d") >= cutoff_date
        }
        cleaned_count = len(self.duplicate_hashes)
        print(f"Pulizia degli UUID: {original_count} UUID iniziali, {cleaned_count} mantenuti dopo il filtro di {self.days_range} giorni")
        self.save_hashes()

    def load_existing_transactions(self, start_date=None, end_date=None):
        """Carica le transazioni esistenti da Firefly III usando solo UUID"""
        print("Caricamento delle transazioni esistenti da Firefly III...")
        if not start_date or not end_date:
            start_date = (datetime.now() - timedelta(days=self.days_range)).strftime('%Y-%m-%d')
            end_date = datetime.now().strftime('%Y-%m-%d')
        page = 1
        params = {'page': page, 'start': start_date, 'end': end_date}
        
        while True:
            try:
                response = requests.get(
                    f"{self.host}/api/v1/transactions",
                    headers=self.headers,
                    params=params
                )
                response.raise_for_status()
                data = response.json()
                transactions = data['data']
                
                if not transactions:
                    break
                    
                for transaction in transactions:
                    for split in transaction['attributes']['transactions']:
                        date = split['date'].split('T')[0]
                        external_id = split.get('external_id', '')
                        if external_id and "tricount" in split.get('tags', []):  # Considera solo transazioni da Tricount
                            self.duplicate_hashes[external_id] = date
                
                if data['meta']['pagination']['current_page'] >= data['meta']['pagination']['total_pages']:
                    break
                page += 1
                params['page'] = page
                
            except Exception as e:
                print(f"Errore nel caricamento delle transazioni: {str(e)}")
                return
                
        self.transactions_loaded = True
        print(f"Caricate {len(self.duplicate_hashes)} transazioni totali (Firefly + locali)")

    def create_transaction_hash(self, date, description, amount, category, uuid=None):
        """Restituisce l'UUID se presente, altrimenti genera un hash"""
        if uuid:
            return uuid
        hash_input = f"{date}|{description.strip().lower()}|{amount}|{category.strip().lower()}"
        return hashlib.md5(hash_input.encode()).hexdigest()

    def get_or_create_category(self, name):
        if not name or name.strip() == "":
            return None
        if name in self.categories_cache:
            return self.categories_cache[name]
        try:
            response = requests.get(f"{self.host}/api/v1/categories", headers=self.headers)
            response.raise_for_status()
            categories = response.json()['data']
            for category in categories:
                if category['attributes']['name'].lower() == name.lower():
                    category_id = category['id']
                    self.categories_cache[name] = category_id
                    return category_id
            response = requests.post(
                f"{self.host}/api/v1/categories",
                headers=self.headers,
                json={"name": name}
            )
            if response.status_code == 422:
                print(f"Attenzione: Impossibile creare la categoria '{name}'.")
                return None
            response.raise_for_status()
            category_id = response.json()['data']['id']
            self.categories_cache[name] = category_id
            return category_id
        except Exception as e:
            print(f"Errore con la categoria '{name}': {str(e)}")
            return None

    def import_transactions(self, transactions_data):
        if not self.transactions_loaded:
            print("Errore: Transazioni esistenti non caricate.")
            return 0, 0, 0
        
        total_transactions = len(transactions_data)
        imported_count = 0
        skipped_count = 0
        error_count = 0
        
        print(f"Inizio importazione di {total_transactions} transazioni...")
        
        for _, row in tqdm(transactions_data.iterrows(), total=total_transactions):
            try:
                uuid = row.get('UUID', '')
                if not uuid:
                    skipped_count += 1
                    print(f"Transazione senza UUID saltata: {row.get('Description', 'N/A')}")
                    continue

                who_paid = row.get('Who Paid', '')
                total_amount = abs(float(row.get('Total', 0)))
                currency = row.get('Currency', 'EUR')
                description = row.get('Description', '') or ''
                if pd.isna(description):
                    description = "Transazione senza etichetta"
                description = description.strip().lower()
                
                when = row.get('When', '')
                if pd.isna(when):
                    transaction_date = datetime.now().strftime('%Y-%m-%d')
                else:
                    transaction_date = pd.Timestamp(when).strftime('%Y-%m-%d')
                
                raw_category = row.get('RawCategory', '') or ''
                category = row.get('Category', '') or ''
                if pd.isna(raw_category):
                    raw_category = ""
                if pd.isna(category):
                    category = ""
                
                # Usa solo UUID per il controllo dei duplicati
                if uuid in self.duplicate_hashes:
                    skipped_count += 1
                    continue
                
                category_id = self.get_or_create_category(category) if category else None
                
                transaction_data = {
                    "type": "withdrawal",
                    "date": transaction_date,
                    "amount": str(total_amount),
                    "currency_code": currency,
                    "description": description,
                    "source_id": str(self.default_account_id),
                    "external_id": uuid,
                    "tags": ["imported", "tricount"]
                }
                
                if category and category.strip():
                    transaction_data["category_name"] = category
                    
                notes = f"Pagato da: {who_paid}"
                involved = row.get('Involved', '')
                if involved and not pd.isna(involved):
                    notes += f"\nCoinvolti: {involved}"
                transaction_data["notes"] = notes
                
                api_data = {
                    "error_if_duplicate_hash": True,
                    "transactions": [transaction_data]
                }
                
                response = requests.post(
                    f"{self.host}/api/v1/transactions",
                    headers=self.headers,
                    json=api_data
                )
                
                if response.status_code == 422:
                    error_message = response.json().get('message', 'Errore sconosciuto')
                    if "duplicate" in error_message.lower():
                        skipped_count += 1
                        self.duplicate_hashes[uuid] = transaction_date
                    else:
                        print(f"Attenzione: Impossibile importare '{description}': {error_message}")
                        error_count += 1
                    continue
                    
                response.raise_for_status()
                self.duplicate_hashes[uuid] = transaction_date
                imported_count += 1
                
            except Exception as e:
                print(f"Errore: {str(e)}")
                error_count += 1
        
        self.save_hashes()
        print(f"Importazione completata: {imported_count} importate, {skipped_count} saltate, {error_count} errori.")
        return imported_count, skipped_count, error_count

def tricount_to_firefly(tricount_key=DEFAULT_TRICOUNT_KEY, firefly_host=DEFAULT_FIREFLY_HOST, firefly_token=DEFAULT_FIREFLY_TOKEN, save_excel=True, days_range=DEFAULT_DAYS_RANGE):
    current_time = datetime.now().strftime("%Y/%m/%d %H:%M")
    print(f"==============::::::: {current_time} :::::::==============")
    
    print("=== FASE 1: Connessione a Tricount ===")
    api = TricountAPI()
    print("Autenticazione con Tricount...")
    api.authenticate()
    print(f"Recupero dati per la chiave: {tricount_key}")
    data = api.fetch_tricount_data(tricount_key)

    with open('response_data.json', 'w') as f:
        json.dump(data, f, indent=2)
    print("Dati grezzi salvati in response_data.json")

    handler = TricountHandler()
    tricount_title = handler.get_tricount_title(data)
    print(f"Elaborazione dati per: {tricount_title}")
    transactions = handler.parse_tricount_data(data)
    
    file_name = f"Transactions {tricount_title}"
    if save_excel:
        df = handler.write_to_excel(transactions, file_name=file_name)
    else:
        df = pd.DataFrame(transactions)
    
    print(f"Estratte {len(transactions)} transazioni da Tricount")
    
    print("\n=== FASE 2: Importazione in Firefly III ===")
    importer = FireflyIIIImporter(firefly_host, firefly_token, days_range)
    imported, skipped, errors = importer.import_transactions(df)
    
    importer.clean_duplicate_hashes()
    
    print("\n=== RIEPILOGO ===")
    print(f"Tricount: {tricount_title}")
    print(f"Transazioni totali: {len(transactions)}")
    print(f"Firefly III: {imported} importate, {skipped} saltate, {errors} errori")
    print("=============================================================")
    print("\n\n")
    
    return imported, skipped, errors

def main():
    parser = argparse.ArgumentParser(description='Importa dati da Tricount a Firefly III')
    parser.add_argument('--tricount-key', default=DEFAULT_TRICOUNT_KEY, help='Chiave Tricount')
    parser.add_argument('--firefly-host', default=DEFAULT_FIREFLY_HOST, help='URL Firefly III')
    parser.add_argument('--firefly-token', default=DEFAULT_FIREFLY_TOKEN, help='Token Firefly III')
    parser.add_argument('--days-range', type=int, default=DEFAULT_DAYS_RANGE, help='Numero di giorni per il range temporale di caricamento e conservazione hash')
    parser.add_argument('--no-excel', action='store_true', help='Non salvare Excel')
    
    args = parser.parse_args()
    
    tricount_to_firefly(
        tricount_key=args.tricount_key,
        firefly_host=args.firefly_host,
        firefly_token=args.firefly_token,
        save_excel=not args.no_excel,
        days_range=args.days_range
    )

if __name__ == "__main__":
    main()
