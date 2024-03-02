import base64
import pickle
import os.path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from bs4 import BeautifulSoup
import re

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


def extract_six_digit_div(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    divs = soup.find_all('div', string=re.compile(r'^\d{6}$'))
    return [div.text for div in divs]


def get_service():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('resource/gmail.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    service = build('gmail', 'v1', credentials=creds)
    return service


def check_latest_email(service, query_email):
    results = service.users().messages().list(userId='me', q=f"from:{query_email}", maxResults=1).execute()
    messages = results.get('messages', [])
    
    if not messages:
        print("No new messages.")
        return None
    
    msg = messages[0]
    txt = service.users().messages().get(userId='me', id=msg['id']).execute()
    
    html_part = None
    for part in txt['payload']['parts']:
        if part['mimeType'] == 'text/html':
            html_part = part
            break

    if not html_part:
        print("No HTML content found.")
        return None

    data = html_part['body']['data']
    decoded_data = base64.urlsafe_b64decode(data)
    digits = extract_six_digit_div(decoded_data.decode('utf-8'))
    if len(digits) == 1:
        if not os.path.exists('resource'):
            os.makedirs('resource')
        if not os.path.exists('resource/code.txt'):
            with open('resource/code.txt', 'w') as f:
                f.write(digits[0])
        else:
            with open('resource/code.txt', 'r') as f:
                previous = f.read()
                if previous == digits[0]:
                    return None
                else:
                    with open('resource/code.txt', 'w') as f:
                        f.write(digits[0])
        
        return digits[0]
    else:
        raise


if __name__ == "__main__":
    service = get_service()
    email_content = check_latest_email(service, "noreply@poe.com")
    if email_content:
        print(email_content)
