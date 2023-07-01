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

    def get_products(self) -> dict[str:str]:
        response = requests.get(self.products_url, headers=self.headers)
        response.raise_for_status()

        response = requests.get(self.products_url.__str__(), headers=headers)
        response.raise_for_status()

        return response.json().get('data')


if __name__ == '__main__':
    env = Env()
    env.read_env()

    elastic = ElasticPath(
        base_url=env.str('ELASTIC_BASE_URL'),
        client_id=env.str('ELASTIC_CLIENT_ID'),
        client_secret=env.str('ELASTIC_CLIENT_SECRET'),
        store_id=env.str('ELASTIC_STORE_ID'),
    )

    print(elastic.get_products())

