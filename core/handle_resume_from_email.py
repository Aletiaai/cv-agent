#core/handle_resume_from_email.py
import os.path
import base64
import os
from email.message import EmailMessage
from email.utils import encode_rfc2231
from googleapiclient.errors import HttpError
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from api_integration.gmail_api import authenticate_gmail_api, verify_credentials
from data.data_handler import format_feedback_content, format_feedback_content_API_call

try:
    verify_credentials()  # Check if credentials.json exists
    service = authenticate_gmail_api()
    # Use the service object for Gmail API operations
except Exception as e:
    print(f"Failed to authenticate: {e}")

def create_draft(user_id, message_body):
    """Creates a draft email in the user's Gmail account.
    Args:service: Authorized Gmail API service instance.
        user_id: User's email address. The special value "me"
        can be used to indicate the authenticated user.
        message_body: The body of the email message, including headers.
    Returns: Draft object, including draft id and message meta data.
    """
    try:
        message = {'message': message_body}
        draft = service.users().drafts().create(userId = user_id, body = message).execute()

        draft_id = draft["id"]
        draft_message = draft["message"]
        draft_message_id = draft["message"]["id"]
        draft_message_thread_id = draft["message"]["threadId"]
        draft_message_label_id = draft["message"]["labelIds"]

        print (f'Draft id: {draft_id}\nDraft message: {draft_message}')
        
        return draft, draft_id, draft_message_id, draft_message_thread_id, draft_message_label_id
    except Exception as e:
        print(f'An error ocurred {e}')
        return None

def send_feedback_email(recipient_email, user_name, feedback):
    """Creates a draft email with the provided feedback."""
    # Create the multipart message
    message = MIMEMultipart()
    message['To'] = recipient_email
    message['From'] = 'marko.garcia@gmail.com'
    message['Subject'] = f"Hola {user_name.title()}, aquí la retro de tu cv"

    # Format the feedback dictionary into readable text
    formatted_feedback = format_feedback_content(feedback)

    # Add body to email
    message.attach(MIMEText(formatted_feedback, 'plain', 'utf-8'))

    # Encode the message for the Gmail API
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode('ascii')

    # Create the draft
    return create_draft("me", {'raw': encoded_message})

def send_feedback_email_2(recipient_email, user_name, feedback):
    """Creates a draft email with an ambedded link to a document. The feedback is already formated for an email"""
    try:
        # Create the multipart message
        message = MIMEMultipart()
        message['To'] = recipient_email
        message['From'] = 'marko.garcia@gmail.com'
        message['Subject'] = f"Hola {user_name.title()}, aquí la retro de tu cv"
        message['Cc'] = 'anaya.rjose@gmail.com' # Add the "cc" recipient

        # Format the feedback dictionary into readable text
        #formatted_feedback = format_feedback_content_API_call(feedback)
        formatted_feedback = feedback.replace("\n", "<br>")

        # Add the extra line with a hyperlink
        #extra_tips_link = "https://drive.google.com/file/d/1DB1bbSw3vruC3r5SbwXyOLJJNmwJO9TD/view?usp=drive_link"  # link to the PDF in drive
        #extra_tips_text = (
        #    "Tenemos un extra para ti, "
        #    f'<a href="{extra_tips_link}">aquí</a> '
        #    "puedes encontrar un documento con tips adicionales que pueden ser de ayuda."
        #)

        # Combine the formatted feedback and the extra tips text
        email_body = f"{formatted_feedback}<br>¡Éxito en tu búsqueda laboral!<br>Iván Anaya y Marco García"

        # Add HTML body to email
        message.attach(MIMEText(email_body, 'html', 'utf-8'))
        

        # Encode the message for the Gmail API
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode('ascii')

        draft_and_info = create_draft("me", {'raw': encoded_message})

        draft, draft_id, draft_message_id, draft_message_thread_id, draft_message_label_id = draft_and_info

        # Create the draft
        return draft, draft_id, draft_message_id, draft_message_thread_id, draft_message_label_id
    except Exception as e:
        print(f"An error occurred while creating the draft email: {e}")
        return None

def questions_email_draft(recipient_email, user_name, email_content):
    try:
        # Create the multipart message
        message = MIMEMultipart()
        message['To'] = recipient_email
        message['From'] = 'marko.garcia@gmail.com'
        message['Subject'] = f"Hola {user_name.title()}, tengo algunas preguntas acerca de tu CV"
        message['Cc'] = 'anaya.rjose@gmail.com' # Add the "cc" recipient

         # Add body to email
        message.attach(MIMEText(email_content, 'plain', 'utf-8'))
        # Encode the message for the Gmail API
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode('ascii')
        # Create the draft
        return create_draft("me", {'raw': encoded_message})
    except Exception as e:
        print(f"An error occurred while creating the draft: {e}")
        return None

def update_draft_with_attachment(draft_id, pdf_path):
    """Updates an existing draft with a PDF attachment.
    Args:draft_id: The ID of the draft to update
        pdf_path: Path to the PDF file to attach
    Returns:Updated draft object or None if there's an error"""
    try:
        # First, get the existing draft
        draft = service.users().drafts().get(userId = "me", id = draft_id, format = 'full').execute()
        # Create a new message from the existing draft
        message = MIMEMultipart()

        # Copy headers from the original message
        original_headers = draft['message']['payload']['headers']
        for header in original_headers:
            if header['name'].lower() in ['to', 'from', 'subject']:
                message[header['name']] = header['value']

        # Get the original message body
        original_body = None
        parts = draft['message']['payload'].get('parts', [])
        if not parts:  # If no parts, the payload itself might be the message
            if draft['message']['payload'].get('body', {}).get('data'):
                original_body = base64.urlsafe_b64decode(
                    draft['message']['payload']['body']['data'].encode('ASCII')
                ).decode('utf-8')
        else:
            for part in parts:
                if part['mimeType'] == 'text/plain':
                    original_body = base64.urlsafe_b64decode(
                        part['body']['data'].encode('ASCII')
                    ).decode('utf-8')
                    break

        # Attach the original body
        if original_body:
             message.attach(MIMEText(original_body, 'plain', 'utf-8'))
        
        # Attach the PDF
        with open(pdf_path, 'rb') as attachment:
            part = MIMEBase('application', 'pdf')
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            
            filename = os.path.basename(pdf_path)
            part.add_header(
                'Content-Disposition',
                'attachment',
                filename = filename
            )
            part.add_header('Content-Type', 'application/pdf')
            message.attach(part)

        # Encode the updated message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('ascii')
        
        # Update the draft
        updated_draft = service.users().drafts().update(
            userId = "me",
            id = draft_id,
            body = {'message': {'raw': raw_message}}
        ).execute()
        
        print(f'Draft updated with attachment: {draft_id}')
        return updated_draft
    
    except Exception as e:
        print(f'An error occurred while updating draft with the attechment: {e}')
        return None

def get_label_id(label_name):
    """Gets the ID of a label by its name.
        Args: label_name: The name of the label.
        Returns:The label ID (or None if not found).
    """
    try:
        results = service.users().labels().list(userId = 'me').execute()
        labels = results.get('labels', [])

        for label in labels:
            if label['name'] == label_name:
                return label['id']

        return None  # Label not found
    except Exception as e:
        print(f'An error occurred: {e}')
        return None

def search_emails(label_ids = None):
    """Searches for emails matching the given query.
    Args: query: The search query (optional).
         label_ids: A list of label IDs to filter by .
    Returns: A list of email message IDs.
    """
    try:
        response = service.users().messages().list(userId = 'me', labelIds=label_ids).execute()
        messages = []
        if 'messages' in response:
            messages.extend(response['messages'])
        
        while 'nextPageToken' in response:
            page_token = response ['nextPageToken']
            response = service.users().messages().list(userId = 'me', labelIds=label_ids, pageToken = page_token).execute()
            messages.extend(response['messages'])

        return [msg['id'] for msg in messages]
    except Exception as e:
        print[f'An error occurred:{e}']
        return[]

def get_message(msg_id):
    """Get a specific email message.
    Args:service: The gmail api service object.
        msg_id: The ID of the message to retrieve.
    Returns:The message object (or none if an error ocurrs)"""
    
    try:
        message = service.users().messages().get(userId = 'me', id = msg_id, format = 'raw').execute()
        #Decode the raw message
        msg_raw = base64.urlsafe_b64decode(message['raw'].encode('ASCII'))
        msg_str = email.message_from_bytes(msg_raw, _class = EmailMessage)

        return msg_str
    except Exception as e:
        print(f'An error ocurred {e}')
        return None

def get_attachments(msg_id, download_dir = "user_resumes"):
    """Downloads attachments from a specific email message.
    Args:service: The Gmail API service object.
        msg_id: The ID of the message containing the attachments.
        download_dir: The directory to save the attachments (default: "user_resumes")."""
    try:
        message = service.users().messages().get(userId = 'me', id = msg_id).execute()
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)

        for part in message['payload']['parts']:
            if part['filename']:
                if 'data' in part['body']:
                    data = part['body']['data']
                else:
                    att_id = part['body']['attachmentId']
                    att = service.users().messages().attachments().get(userId = 'me', messageId = msg_id, id = att_id).execute()
                    data = att['data']
                file_data = base64.urlsafe_b64decode(data.encode('UTF-8'))
                filepath = os.path.join(download_dir, part['filename'])

                with open(filepath, 'wb') as f:
                    f.write(file_data)
                print(f"Attachment saved to: {filepath}")

    except Exception as e:
        print(f'An error occurred: {e}')

