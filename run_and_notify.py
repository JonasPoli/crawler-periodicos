#!/usr/bin/env python3
import sys
import os
import subprocess
import time

# Add parent directory to path to import database modules
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from database import get_session, Journal

def get_journal_name(journal_id):
    try:
        session = get_session()
        journal = session.query(Journal).filter(Journal.id == journal_id).first()
        name = journal.name if journal else None
        session.close()
        return name
    except Exception:
        return None

def send_macos_notification(title, message):
    try:
        # Escape quotes for AppleScript
        escaped_title = title.replace('"', '\\"')
        escaped_message = message.replace('"', '\\"')
        script = f'display notification "{escaped_message}" with title "{escaped_title}"'
        subprocess.run(["osascript", "-e", script], check=False)
    except Exception as e:
        print(f"Erro ao enviar notificação macOS: {e}")

def speak_message(message):
    try:
        subprocess.run(["say", message], check=False)
    except Exception as e:
        print(f"Erro ao falar mensagem: {e}")

def main():
    if len(sys.argv) < 2:
        print("Uso: python run_and_notify.py <journal_id>")
        print("Exemplo: python run_and_notify.py 26")
        sys.exit(1)

    try:
        journal_id = int(sys.argv[1])
    except ValueError:
        print("Erro: O ID da revista deve ser um número inteiro.")
        sys.exit(1)

    journal_name = get_journal_name(journal_id)
    if not journal_name:
        journal_name = f"Revista ID {journal_id}"
    
    print(f"==================================================")
    print(f" INICIANDO CRAWLER PARA: {journal_name}")
    print(f" ID da Revista: {journal_id}")
    print(f"==================================================")
    
    os.makedirs("logs", exist_ok=True)
    log_filepath = f"logs/journal_{journal_id}.log"
    print(f"Os logs detalhados serão salvos em: {log_filepath}\n")

    # Use the local virtual environment's python if available
    python_bin = "python3"
    if os.path.exists("venv/bin/python"):
        python_bin = "venv/bin/python"

    cmd = [python_bin, "run_fast.py", "super", "--id", str(journal_id)]
    
    # Send a notification that the process started
    send_macos_notification("Crawler Iniciado", f"Processo iniciado para {journal_name}")
    
    start_time = time.time()
    
    try:
        # Run the process and capture output, redirecting it to log file while streaming to stdout
        with open(log_filepath, "w", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            # Stream output in real-time
            for line in process.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                log_file.write(line)
                log_file.flush()
                
            process.wait()
            exit_code = process.returncode

    except KeyboardInterrupt:
        print("\n\nProcesso interrompido pelo usuário (Ctrl+C).")
        elapsed = time.time() - start_time
        mins, secs = divmod(int(elapsed), 60)
        msg = f"O processo da {journal_name} foi cancelado pelo usuário após {mins}m {secs}s."
        send_macos_notification("Crawler Cancelado", msg)
        speak_message(f"O processo da {journal_name} foi cancelado.")
        sys.exit(130)

    elapsed_time = time.time() - start_time
    minutes, seconds = divmod(int(elapsed_time), 60)
    time_str = f"{minutes} minutos e {seconds} segundos" if minutes > 0 else f"{seconds} segundos"

    if exit_code == 0:
        status_msg = f"concluído com sucesso"
        notification_title = "Crawler Concluído 🎉"
    else:
        status_msg = f"parou com código de erro {exit_code}"
        notification_title = "Crawler Parou (Erro) ⚠️"

    msg = f"O processo da revista '{journal_name}' {status_msg} após rodar por {time_str}."
    print(f"\n==================================================")
    print(f" {notification_title.upper()}")
    print(f" {msg}")
    print(f"==================================================")
    
    # Send system notification and voice announcement
    send_macos_notification(notification_title, msg)
    speak_message(f"Atenção: O processo de coleta da revista {journal_name} {status_msg}.")

if __name__ == "__main__":
    main()
