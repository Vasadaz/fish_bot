from datetime import datetime
from pathlib import Path

import requests


class ElasticPath:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
    ):
        self.base_url = base_url
        self.client_id = client_id
        self.client_secret = client_secret

        self.access_url = self.base_url + '/oauth/access_token/{path}'
        self.products_url = self.base_url + '/catalog/products/'
        self.carts_url = self.base_url + '/v2/carts/'
        self.files_url = self.base_url + '/v2/files/'
        self.customers_url = self.base_url + '/v2/customers/'

        self.access_token = self._get_access()


    def _get_access(self) -> str:
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'grant_type': 'client_credentials',
        }

        response = requests.post(self.access_url, data=data)
        response.raise_for_status()
        response_notes = response.json()

        self.access_token_expires = response_notes.get('expires')

        return  f'{response_notes.get("token_type")} {response_notes.get("access_token")}'

    def _get_headers(self) -> dict[str:str]:
        if self.access_token_expires <= datetime.utcnow().timestamp():
            self.access_token = self._get_access()
        return {'Authorization': self.access_token}

    def _get_json_headers(self) -> dict[str:str]:
        return {**self._get_headers(), 'Content-Type': 'application/json'}
        
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

    def add_product_to_cart(self, customer_id: str, product_id: str, quantity: str | int) -> None:
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
            f'{self.carts_url}{customer_id}/items',
            headers=self._get_json_headers(),
            json=product_data,
        )
        response.raise_for_status()

    def clear_cart(self, customer_id: str) -> None:
        for product_notes in self.get_cart_items(customer_id).get('products'):
            self.delete_product_from_cart(customer_id, product_notes.get('id'))

    def create_customer(self, email: str, name: str) -> str:
        email = email.strip()
        name = name.strip()

        customer_data = {
            'data': {
                'type': 'customer',
                'email': email,
                'name': name,
            },
        }

        response = requests.post(
            self.customers_url,
            headers=self._get_json_headers(),
            json=customer_data
        )
        response.raise_for_status()

        return response.json().get('data').get('id')

    def create_customer_cart(self, customer_id: str) -> None:
        cart_association_notes = {
            'data': [{
                'type': 'customer',
                'id': customer_id,
            }],
        }

        response = requests.post(
            f'{self.carts_url}{self.get_cart_id(customer_id)}/relationships/customers/',
            headers=self._get_json_headers(),
            json=cart_association_notes,
        )
        response.raise_for_status()

    def create_order(self, customer_id: str) -> None:
        address_notes = {
            'first_name': self.get_customer_name(customer_id),
            'last_name': '',  # Обязательное поле: Фамилия получателя счета.
            'line_1': '',  # Обязательное поле: Первая строка платежного адреса.
            'region': '',  # Обязательное поле: Указывает регион адреса выставления счетов.
            'postcode': '',  # Обязательное поле: Почтовый индекс платежного адреса.
            'country': '',  # Обязательное поле: Указывает страну адреса выставления счетов.
        }
        order_notes = {
            'data': {
                'customer': {'id': customer_id},
                'billing_address': address_notes,
                'shipping_address': address_notes,
            }
        }

        response = requests.post(
            f'{self.carts_url}{self.get_cart_id(customer_id)}/checkout/',
            headers=self._get_json_headers(),
            json=order_notes,
        )
        response.raise_for_status()

    def delete_product_from_cart(self, customer_id: str, product_id: str) -> None:
        response = requests.delete(
            f'{self.carts_url}{customer_id}/items/{product_id}',
            headers=self._get_headers()
        )
        response.raise_for_status()

    def get_cart_id(self, customer_id: str) -> str:
        response = requests.get(
            f'{self.carts_url}{customer_id}',
            headers=self._get_headers(),
        )
        response.raise_for_status()

        return response.json().get('data').get('id')

    def get_cart_items(self, customer_id: str) -> dict[str:str]:
        response = requests.get(
            f'{self.carts_url}{customer_id}/items',
            headers=self._get_headers()
        )
        response.raise_for_status()
        response_notes = response.json()

        cart_notes = {
            'cart_amount': response_notes.get('meta').get('display_price').get('with_tax').get('amount'),
            'products': [],
        }

        for item_notes in response_notes.get('data'):
            cart_notes['products'].append({
                'id': item_notes.get('id'),
                'name': item_notes.get('name'),
                'quantity': item_notes.get('quantity'),
                'amount': item_notes.get('value').get('amount'),
            })

        return cart_notes

    def get_customer_email(self, customer_id: str) -> str:
        response = requests.get(
            f'{self.customers_url}{customer_id}',
            headers=self._get_headers(),
        )
        response.raise_for_status()

        return response.json().get('data').get('email')


    def get_customer_name(self, customer_id: str) -> str:
        response = requests.get(
            f'{self.customers_url}{customer_id}',
            headers=self._get_headers(),
        )
        response.raise_for_status()

        return response.json().get('data').get('name')

    def get_image_path(self, image_id) -> str:
        dir_path = Path('images')
        dir_path.mkdir(parents=True, exist_ok=True)

        for file_path in dir_path.iterdir():
            if image_id == file_path.stem:
                return file_path.as_posix()

        response = requests.get(
            f'{self.files_url}{image_id}',
            headers=self._get_headers(),
        )
        response.raise_for_status()
        download_url = response.json().get('data').get('link').get('href')
        save_path = Path(dir_path) / Path(download_url).name

        download = requests.get(download_url)
        download.raise_for_status()

        with open(save_path, 'wb') as file:
            file.write(download.content)

        return save_path.as_posix()

    def get_product_notes(self, product_id) -> dict[str:str]:
        response = requests.get(
            f'{self.products_url}{product_id}',
            headers=self._get_headers(),
        )
        response.raise_for_status()

        return self._serialize_product_notes(response.json().get('data'))

    def get_products(self) -> list[dict[str:str|int]]:
        products = []

        response = requests.get(
            self.products_url,
            headers=self._get_headers(),
        )
        response.raise_for_status()

        for product_notes in response.json().get('data'):
            products.append(self._serialize_product_notes(product_notes))

        return products

    def update_customer_email(self, customer_id: str, email: str) -> None:
        email = email.strip()

        customer_notes = {
            'data': {
                'type': 'customer',
                'email': email,
            }
        }

        response = requests.put(
            f'{self.customers_url}{customer_id}',
            headers=self._get_json_headers(),
            json=customer_notes,
        )
        response.raise_for_status()
