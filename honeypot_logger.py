import os
import time
import json
from datetime import datetime
import subprocess
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import asyncio
from supabase import create_client, Client

class HoneypotLogger:
    def __init__(self, supabase_url: str, supabase_key: str):
        self.supabase: Client = create_client(supabase_url, supabase_key)
        
    async def log_to_supabase(self, table_name: str, data: dict):
        try:
            self.supabase.table(table_name).insert(data).execute()
        except Exception as e:
            print(f"Error logging to Supabase: {str(e)}")
            
class FileMonitor(FileSystemEventHandler):
    def __init__(self, logger: HoneypotLogger):
        self.logger = logger

    def on_any_event(self, event):
        if event.is_directory:
            return
            
        event_data = {
            'timestamp': datetime.now().isoformat(),
            'event_type': event.event_type,
            'path': event.src_path,
            'user': subprocess.getoutput('whoami'),
            'hostname': subprocess.getoutput('hostname')
        }
        
        asyncio.create_task(self.logger.log_to_supabase('file_events', event_data))

class SSHMonitor:
    def __init__(self, logger: HoneypotLogger):
        self.logger = logger
        self.auth_log = "/var/log/auth.log"

    async def monitor_ssh(self):
        while True:
            try:
                process = await asyncio.create_subprocess_exec(
                    'tail', '-F', self.auth_log,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break
                        
                    line = line.decode().strip()
                    if "sshd" in line:
                        event_data = {
                            'timestamp': datetime.now().isoformat(),
                            'log_entry': line,
                            'hostname': subprocess.getoutput('hostname')
                        }
                        
                        # Extract IP address if present
                        ip = subprocess.getoutput(f"grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' <<< '{line}'")
                        if ip:
                            event_data['ip_address'] = ip
                            
                        # Extract username if present
                        if "Failed password for" in line:
                            username = line.split("Failed password for")[-1].split("from")[0].strip()
                            event_data['username'] = username
                            
                        await self.logger.log_to_supabase('ssh_events', event_data)
                        
            except Exception as e:
                print(f"SSH monitoring error: {str(e)}")
                await asyncio.sleep(5)

class MySQLMonitor:
    def __init__(self, logger: HoneypotLogger):
        self.logger = logger
        
    async def monitor_mysql(self):
        mysql_log = "/var/log/mysql/mysql.log"
        
        while True:
            try:
                process = await asyncio.create_subprocess_exec(
                    'tail', '-F', mysql_log,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break
                        
                    line = line.decode().strip()
                    event_data = {
                        'timestamp': datetime.now().isoformat(),
                        'log_entry': line,
                        'hostname': subprocess.getoutput('hostname')
                    }
                    
                    await self.logger.log_to_supabase('mysql_events', event_data)
                    
            except Exception as e:
                print(f"MySQL monitoring error: {str(e)}")
                await asyncio.sleep(5)

async def main():
    # Initialize logger with your Supabase credentials
    logger = HoneypotLogger(
        supabase_url="YOUR_SUPABASE_URL",
        supabase_key="YOUR_SUPABASE_KEY"
    )
    
    # Set up file monitoring
    file_monitor = FileMonitor(logger)
    observer = Observer()
    paths_to_monitor = ["/etc", "/var/www", "/home"]
    for path in paths_to_monitor:
        if os.path.exists(path):
            observer.schedule(file_monitor, path, recursive=True)
    observer.start()
    
    # Set up SSH and MySQL monitoring
    ssh_monitor = SSHMonitor(logger)
    mysql_monitor = MySQLMonitor(logger)
    
    # Run all monitors concurrently
    await asyncio.gather(
        ssh_monitor.monitor_ssh(),
        mysql_monitor.monitor_mysql()
    )

if __name__ == "__main__":
    asyncio.run(main())
