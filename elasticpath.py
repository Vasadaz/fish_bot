from pathlib import Path

import requests

from environs import Env


class ElasticPath:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        store_id: str,
    ):
        self.base_url = base_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.store_id = store_id

        self.access_url = self.base_url + '/oauth/access_token/'
        self.products_url = self.base_url + '/catalog/products/'
        self.carts_url = self.base_url + '/v2/carts/'
        self.files_url = self.base_url + '/v2/files/'
        self.customers_url = self.base_url + '/v2/customers/'

        self.access_token = self._get_access()
        self.headers = {'Authorization': self.access_token}

    def _get_access(self) -> str:
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'grant_type': 'client_credentials',
        }

        response = requests.post(self.access_url, data=data)
        response.raise_for_status()
        response = response.json()

        return  f'{response["token_type"]} {response["access_token"]}'

    @staticmethod
    def _serialize_product_notes(product_notes) -> dict[str:str|int]:
        product_attributes = product_notes.pop('attributes')
        product_relationships = product_notes.pop('relationships')

        return {
            'id': product_notes.get('id'),
            'name': product_attributes.get('name'),
            'sku': product_attributes.get('sku'),
            'description': product_attributes.get('description'),
            'price': product_attributes.get('price').get('USD').get('amount'),
            'main_image_id': product_relationships.get('main_image').get('data').get('id'),
        }

    def add_product_to_cart(self, product_id, quantity) -> None:
        headers = {
            **self.headers,
            'Content-Type': 'application/json',
        }

        product_notes = self.get_product_notes(product_id)

        product_data = {
            'data': {
                'type': 'custom_item',
                'name': product_notes.get('name'),
                'sku': product_notes.get('sku'),
                'description': product_notes.get('description'),
                'quantity': quantity,
                'price': {
                    'amount': product_notes.get('price'),
                },
            },
        }

        response = requests.post(
            self.carts_url + f'{self.client_id}/items',
            headers=headers,
            json=product_data,
        )
        response.raise_for_status()

    def clear_cart(self) -> None:
        for product_notes in self.get_cart_items().get('products'):
            self.delete_product_from_cart(product_notes.get('id'))

    def create_customer(self, email: str, name: str):
        email = email.strip()
        name = name.strip()
        headers = {
            **self.headers,
            'Content-Type': 'application/json',
        }

        customer_data = {
            'data': {
                'type': 'customer',
                'email': email,
                'name': name,
            },
        }

        customer_response = requests.get(
            self.customers_url,
            headers=headers,
            params={'filter': f'eq(email,{email})'}
        )

        customer_response = requests.post(self.customers_url, headers=headers,  json=customer_data)
        customer_response.raise_for_status()

        customer_id = customer_response.json().get('data').get('id')

        return customer_id

    def create_customer_cart(self, email: str, name: str):
        email = email.strip()
        name = name.strip()
        headers = {
            **self.headers,
            'Content-Type': 'application/json',
        }
        cart_association_notes = {
            'data':[{
                'type': 'customer',
                'id': self.get_customer_id(email, name),
            }],
        }

        response = requests.post(
            self.carts_url + f'{self.get_cart_id()}/relationships/customers/',
            headers=headers,
            json=cart_association_notes,
        )
        response.raise_for_status()

        return

    def delete_product_from_cart(self, product_id) -> None:
        response = requests.delete(self.carts_url + f'{self.client_id}/items/' + product_id, headers=self.headers)
        response.raise_for_status()

    def get_cart_id(self) -> str:
        response = requests.get(self.carts_url + self.client_id, headers=self.headers)
        response.raise_for_status()


        return response.json().get('data').get('id')

    def get_cart_items(self) -> dict[str:str]:
        response = requests.get(self.carts_url + f'{self.client_id}/items', headers=self.headers)
        response.raise_for_status()
        cart_items = response.json()

        cart_notes = {
            'cart_amount': cart_items.get('meta').get('display_price').get('with_tax').get('amount'),
            'products': [],
        }

        response = requests.get(self.carts_url + self.client_id, headers=self.headers)
        response.raise_for_status()

        for item_notes in cart_items.get('data'):
            cart_notes['products'].append({
                'id': item_notes.get('id'),
                'name': item_notes.get('name'),
                'quantity': item_notes.get('quantity'),
                'amount': item_notes.get('value').get('amount'),
            })

        return cart_notes

    def get_customer_id(self, email: str, name: str) -> str:
        email = email.strip()
        name = name.strip()

        payload = {'filter': f'eq(email,{email})'}

        response = requests.get(self.customers_url, headers=self.headers, params=payload)
        response.raise_for_status()

        for customer_notes in response.json().get('data'):
            if customer_notes['email'] == email:
                return customer_notes['id']

        return self.create_customer(email, name)

    def get_image_path(self, image_id) -> str:
        dir_path = Path('images')
        dir_path.mkdir(parents=True, exist_ok=True)

        for file_path in dir_path.iterdir():
            if image_id == file_path.stem:
                return file_path.as_posix()

        response = requests.get(self.files_url + image_id, headers=self.headers)
        response.raise_for_status()
        download_url = response.json().get('data').get('link').get('href')
        save_path = Path(dir_path) / Path(download_url).name

        download = requests.get(download_url)
        download.raise_for_status()

        with open(save_path, 'wb') as file:
            file.write(download.content)

        return save_path.as_posix()

    def get_product_notes(self, product_id) -> dict[str:str]:
        response = requests.get(self.products_url + product_id, headers=self.headers)
        response.raise_for_status()

        return self._serialize_product_notes(response.json().get('data'))

    def get_products(self) -> list[dict[str:str|int]]:
        response = requests.get(self.products_url, headers=self.headers)
        response.raise_for_status()

        products = []
        for product_notes in response.json().get('data'):
            products.append(self._serialize_product_notes(product_notes))

        return products

