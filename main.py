import subprocess
import sys
import requests
import json
import sqlite3
import time
import schedule


class OLXMonitor:
    def __init__(self, config_file_path="config.json"):
        self.config_file_path = config_file_path
        self.OLX_COMMAND, self.DATABASE_FILE, self.INCLUDE_FILTERS, self.EXCLUDE_FILTERS = self.read_config()

    def read_config(self):
        with open(self.config_file_path, "r") as config_file:
            config_data = json.load(config_file)
            return (
                config_data.get("olx_command"),
                config_data.get("database_file"),
                config_data.get("include_filters", []),
                config_data.get("exclude_filters", []),
            )

    def create_table(self):
        connection = sqlite3.connect(self.DATABASE_FILE)
        cursor = connection.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS olx_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE,
                title TEXT,
                price TEXT,
                location TEXT,
                date TEXT
            )
        ''')

        connection.commit()
        connection.close()

    def execute_olx_command(self, olx_command):
        try:
            process = subprocess.Popen(olx_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            output, error = process.communicate()

            if process.returncode == 0:
                return json.loads(output.decode())
            else:
                print(f"Error executing OLX command: {error.decode()}")
                return None
        except Exception as e:
            print(f"Exception during command execution: {e}")
            return None

    def insert_new_items(self, items):
        connection = sqlite3.connect(self.DATABASE_FILE)
        cursor = connection.cursor()

        for item in items:
            if self._is_item_allowed(item):
                try:
                    item['price'] = item['price'].replace(".css-1c0ed4l{display:inline-block;}.css-1ojrdd5{height:24px;width:24px;margin-right:8px;color:#002F34;}", "")
                    cursor.execute('''
                        INSERT INTO olx_items (url, title, price, location, date)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (item['url'], item['title'], item['price'], item['location'], item['date']))
                    print(f"Title: {item['title']}")
                    print(f"Price: {item['price']}")
                except sqlite3.IntegrityError:
                    # Item already exists in the database
                    pass

        connection.commit()
        connection.close()

    def _is_item_allowed(self, item):
        return (
            all(keyword.lower() in item['title'].lower() for keyword in self.INCLUDE_FILTERS) and
            not any(keyword.lower() in item['title'].lower() for keyword in self.EXCLUDE_FILTERS)
        )

    def remove_missing_items(self, latest_json_urls):
        connection = sqlite3.connect(self.DATABASE_FILE)
        cursor = connection.cursor()

        cursor.execute("SELECT url FROM olx_items")
        existing_urls = set(row[0] for row in cursor.fetchall())

        urls_to_remove = existing_urls - set(latest_json_urls)

        for url in urls_to_remove:
            cursor.execute("DELETE FROM olx_items WHERE url = ?", (url,))

        connection.commit()
        connection.close()

    def check_for_new_items(self):
        json_data = self.execute_olx_command(self.OLX_COMMAND)

        if json_data:
            connection = sqlite3.connect(self.DATABASE_FILE)
            cursor = connection.cursor()

            cursor.execute("SELECT url FROM olx_items")
            existing_urls = set(row[0] for row in cursor.fetchall())

            filtered_items = [item for item in json_data if self._is_item_allowed(item)]
            new_items = [item for item in filtered_items if item['url'] not in existing_urls]

            if new_items:
                print("New items detected!")
                self.insert_new_items(new_items)
                latest_json_urls = set(item['url'] for item in filtered_items)
                self.remove_missing_items(latest_json_urls)
                self.send_discord_webhook_notification(new_items)

            connection.close()

    def send_discord_webhook_notification(self, new_items):
        webhook_url = ""

        payload = {
            "content": "New items detected!",
            "embeds": [
                {
                    "title": "New Items",
                    "color": 16711680,
                    "fields": [
                        {"name": f"Item {index + 1}", "value": f"[{item['title']}]({item['url']})\nPrice: {item['price']}\nLocation: {item['location']}\nDate: {item['date']}", "inline": False}
                        for index, item in enumerate(new_items)
                    ]
                }
            ]
        }

        try:
            response = requests.post(webhook_url, json=payload)
            response.raise_for_status()
            print("Discord webhook notification sent successfully!")
        except requests.exceptions.RequestException as e:
            print(f"Error sending Discord webhook notification: {e}")


if __name__ == "__main__":
    olx_monitor = OLXMonitor()

    olx_monitor.create_table()
    olx_monitor.check_for_new_items()

    schedule.every().hour.do(olx_monitor.check_for_new_items)

    while True:
        schedule.run_pending()
        time.sleep(1)
