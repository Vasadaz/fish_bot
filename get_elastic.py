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

response_auth = requests.post(ELASTIC_BASE_URL + '/oauth/access_token', data=data)
response_auth.raise_for_status()
response_auth = response_auth.json()
print(response_auth)

headers_auth = {
    'Authorization': f'{response_auth["token_type"]} {response_auth["access_token"]}',
}

response_products = requests.get(ELASTIC_BASE_URL + '/pcm/products', headers=headers_auth)
response_products.raise_for_status()
print(response_products.json())


data = {
    "bundle_configuration": {
        "selected_options": {
               "d298429b-a17d-45da-aca5-dac2c5abb604": 1
        }

    }
}

response = requests.post(ELASTIC_BASE_URL + '/v2/carts', data=data, headers=headers_auth)
response.raise_for_status()

