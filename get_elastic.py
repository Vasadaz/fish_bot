from pprint import pprint as print
import requests

from environs import Env

env = Env()
env.read_env()

ELASTIC_BASE_URL = env.str('ELASTIC_BASE_URL')
ELASTIC_CLIENT_ID = env.str('ELASTIC_CLIENT_ID')
ELASTIC_CLIENT_SECRET = env.str('ELASTIC_CLIENT_SECRET')
ELASTIC_STORE_ID = env.str('ELASTIC_STORE_ID')


data = {
    'client_id': ELASTIC_CLIENT_ID,
    'client_secret': ELASTIC_CLIENT_SECRET,
    'grant_type': 'client_credentials',
}


response = requests.post(ELASTIC_BASE_URL + '/oauth/access_token', data=data)
response.raise_for_status()
response = response.json()
print(response)

headers = {
    'Authorization': f'{response["token_type"]} {response["access_token"]}',
}



response = requests.get(ELASTIC_BASE_URL + '/pcm/products', headers=headers)
response.raise_for_status()
#print(response.json())


data = {
    'client_id': ELASTIC_CLIENT_ID,
    'grant_type': 'implicit',
}

response = requests.post(ELASTIC_BASE_URL + '/oauth/access_token', data=data)
response.raise_for_status()
print(response.json())
response = response.json()


headers = {
    'Authorization': f'{response["token_type"]} {response["access_token"]}',
    'Content-Type': 'application/json',
}

data = {
    "type": "token",
    "email": "ron@swanson.com",
    "password": "mysecretpassword",
    "authentication_mechanism": "password"
}

response = requests.post(ELASTIC_BASE_URL + '/v2/customers/tokens', data=data, headers=headers)
response.raise_for_status()

