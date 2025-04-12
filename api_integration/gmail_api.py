#api_integration/gmail_api.py

from __future__ import print_function
import os.path
import logging
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.exceptions import RefreshError

#Se tup logging 
logging.basicConfig(level = logging.INFO)
logger = logging.getLogger(__name__)


#If modifying these scopes, delete the file token.json
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/drive.readonly'
    ]

def authenticate_gmail_api():
    """Authenticates the user for Gmail API access and returns the service object.
        Handles token refresh and authentication errors. """
    creds = None
    try:
        #check if token json exist
        if os.path.exists('token.json'):
            try:
                creds = Credentials.from_authorized_user_file('token.json', SCOPES)
            except Exception as e:
                logger.error(f"Error loading credentials from token.json: {e}")
                os.remove('token.json') #remove invalid token file
                creds = None
        #If there are no valid credentials available, authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except RefreshError:
                    logger.info("Token refresh failed, initiating new authentication flow")
                    creds = None
                except Exception as e:
                    logger.error(f"Error refreshing credentials: {e}")
                    creds = None
            #If refreshe failed or no credentials exist, start new auth flow
            if not creds:
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        'credentials.json', SCOPES)
                    creds = flow.run_local_server(port = 0)

                    #Save the credentials for the next run
                    with open ('token.json', 'w') as token:
                        token.write(creds.to_json())
                        logger.info("New credentials saved successfully")
                except Exception as e:
                    logger.error(f"Error in authentication flow: {e}")
                    raise
        #Build and return the Gmail service
        return build('gmail', 'v1', credentials = creds)
    except Exception as e:
            logger.error(f"Authentication failed: {e}")
            raise

def verify_credentials():
    """Utility function to verify if credentials.json exists"""
    if not os.path.exists('credentials.json'):
        raise FileNotFoundError(
            "credentials.json not found. Please download if from Google Cloud Console "
            "and place it in the root directory of your project."
        )