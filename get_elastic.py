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
#print(response_auth)

headers_auth = {
    'Authorization': f'{response_auth["token_type"]} {response_auth["access_token"]}',
}


response_products = requests.get(ELASTIC_BASE_URL + '/catalog/products', headers=headers_auth)
response_products.raise_for_status()
response_products = response_products.json()
#print(response_products)

product_1 = response_products['data'][0]['id']
product_2 = response_products['data'][1]['id']
product_3 = response_products['data'][2]['id']

response_product_1 = requests.get(ELASTIC_BASE_URL + f'/catalog/products/{product_1}', headers=headers_auth)
response_product_1.raise_for_status()
response_product_1 = response_product_1.json().get('data').get('attributes')
print(response_product_1)

response_product_2 = requests.get(ELASTIC_BASE_URL + f'/catalog/products/{product_1}', headers=headers_auth)
response_product_2.raise_for_status()
response_product_2 = response_product_2.json().get('data').get('attributes')
print(response_product_2)

response_product_3 = requests.get(ELASTIC_BASE_URL + f'/catalog/products/{product_1}', headers=headers_auth)
response_product_3.raise_for_status()
response_product_3 = response_product_3.json().get('data').get('attributes')
print(response_product_3)

client_id = 323232

response_cart = requests.get(ELASTIC_BASE_URL + f'/v2/carts/{client_id}', headers=headers_auth)
response_cart.raise_for_status()
print(response_cart.json())

headers_cart = {
    'Authorization': f'{response_auth["token_type"]} {response_auth["access_token"]}',
    'Content-Type': 'application/json',
}

data_1 = {
            'data': {
                'type': 'custom_item',
                'name': response_product_1.get('name'),
                'sku': response_product_1.get('sku'),
                'description': response_product_1.get('description', 'Нет описания'),
                'quantity': 5,
                'price': {
                    'amount': response_product_1.get('price').get('USD').get('amount'),
                },
            },
        }

response = requests.post(ELASTIC_BASE_URL + f'/v2/carts/{client_id}/items', json=data_1, headers=headers_cart)
response.raise_for_status()

response_cart = requests.get(ELASTIC_BASE_URL + f'/v2/carts/{client_id}/items', headers=headers_auth)
response_cart.raise_for_status()
print(response_cart.json())