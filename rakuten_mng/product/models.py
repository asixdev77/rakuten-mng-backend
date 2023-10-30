import requests
import uuid
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from dry_rest_permissions.generics import authenticated_users
from PIL import Image
from django.utils.crypto import get_random_string

from utils.rms_api import CabinetAPI, ItemAPI, InventoryAPI
from utils.profit_util import calc_sell_price


class Product(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'Draft' # Not Publish yet
        INACTIVE = 'Inactive' # Publish, but not Active
        ACTIVE = 'Active' # Publish, Active

    class Condition(models.TextChoices):
        NEW = 'new_new'

    class ShippingMethod(models.TextChoices):
        SHIPPINGMAIL = 'shipping_mail'
        SHIPPING60 = 'shipping_60'
        SHIPPING80 = 'shipping_80'
        SHIPPING100 = 'shipping_100'
        SHIPPING120 = 'shipping_120'

    status = models.CharField(
        _('status'),
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT
    )
    source_url = models.TextField(_('url'), null=True, blank=True)
    jan = models.CharField(
        _('JAN'),
        max_length=50,
        null=True,
        blank=True
    )
    manage_number = models.CharField(
        _("manage Number"),
        max_length=255,
        null=True,
        blank=True
    )
    title = models.CharField(
        _('title'),
        max_length=255,
        null=True,
        blank=True
    )
    condition = models.CharField(
        _('condition'),
        max_length=20,
        blank=True,
        choices=Condition.choices
    )
    buy_price = models.IntegerField(
        _('buy Price'),
        null=True,
        blank=True
    )
    sell_price = models.IntegerField(
        _('sell Price'),
        null=True,
        blank=True
    )
    shipping_method = models.CharField(
        _("shipping Method"),
        choices=ShippingMethod.choices,
        default=ShippingMethod.SHIPPINGMAIL
    )
    shipping_fee = models.IntegerField(
        _("shipping Fee"),
        null=True,
        blank=True
    )
    rakuten_fee = models.IntegerField(
        _("rakuten Fee"),
        null=True,
        blank=True
    )
    point = models.IntegerField(
        _("point"),
        null=True,
        blank=True,
    )
    profit = models.IntegerField(
        _("profit"),
        null=True,
        blank=True
    )
    count_set = models.IntegerField(
        _('count Set'),
        null=True,
        blank=True,
    )
    quantity = models.IntegerField(
        _('quantity'),
        null=True,
        blank=True
    )
    description = models.TextField(
        _('description'),
        null=True,
        blank=True
    )
    created_by = models.ForeignKey(
        "users.user",
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    @classmethod
    def save_product(cls, data, products, created_by):
        shipping_fee = ProductSetting.objects.get(created_by=created_by).shipping_mail_fee or 0
        sell_price = calc_sell_price(
            buy_price=data['price'],
            count_set=data['count_set'],
            shipping_fee=shipping_fee,
        )
        rakuten_fee = int((ProductSetting.objects.get(created_by=created_by).rakuten_fee or 0)*sell_price/100)
        product = Product(
            status=Product.Status.DRAFT,
            source_url=data['source_url'],
            jan=data['jan'],
            title=data['title'],
            description=data['description'],
            condition=Product.Condition.NEW,
            # TODO
            # condition=data['condition'],
            sell_price=sell_price,
            buy_price=data['price'],
            quantity=data['quantity'],
            count_set=data['count_set'],
            point=1, # Default Value in RMS
            profit=500, # Defalut Value
            shipping_fee=shipping_fee,
            rakuten_fee=rakuten_fee,
            created_by=created_by
        )
        product.save()

        # Photo
        photos = data['photos']
        for (index, photo) in enumerate(photos):
            image = requests.get(photo['url'])
            random_name = uuid.uuid1()
            with open(str(settings.APPS_DIR/ f'media/productphoto/{random_name}.png'), 'wb') as f:
                f.write(image.content)
            image = Image.open(str(settings.APPS_DIR/ f'media/productphoto/{random_name}.png'))
            productphoto = ProductPhoto(
                product=product,
                path=f'productphoto/{random_name}.png',
                width=image.width,
                height=image.height
            )
            productphoto.save()
            if index >= 8:
                break # Amazon allows maximium 9 Images
        products.append(product)

    def insert_to_rms(self, service_secret, license_key):
        # Insert Images
        cabinet_api = CabinetAPI(service_secret, license_key)
        success_images = []
        for photo in self.productphoto_set.all():
            file_name = str(photo.path).split('/')[-1]
            file_path = f'{get_random_string(15).lower()}.jpg'
            with open(file=str(settings.APPS_DIR/ f'media/{str(photo.path)}'), mode='rb') as f:
                file_content = f.read()
            img_data = {
                'xml': (
                    None,  # File data is None because this is not a file field
                    f'''<?xml version='1.0' encoding='UTF-8'?>
                    <request>
                        <fileInsertRequest>
                            <file>
                                <fileName>画像</fileName>
                                <folderId>0</folderId>
                                <filePath>{file_path}</filePath>
                                <overWrite>true</overWrite>
                            </file>
                        </fileInsertRequest>
                    </request>''',
                ),
                'file': (
                    file_name,  # File field name and filename
                    file_content,  # Binary image file data
                ),
            }
            resp = cabinet_api.insert_image(data=img_data)
            if resp.status_code == 200:
                success_images.append(file_path)

        # Insert Item
        item_api = ItemAPI(service_secret, license_key)
        if self.jan:
            manage_number = f'{self.jan}-{self.count_set}'
        else:
            manage_number = get_random_string(15).lower()

        shipping_fee = ProductSetting.objects.get(created_by=self.created_by).shipping_mail_fee or 0
        sell_price = calc_sell_price(
            buy_price=self.buy_price,
            count_set=self.count_set,
            shipping_fee=shipping_fee
        )
        rakuten_fee = int((ProductSetting.objects.get(created_by=self.created_by).rakuten_fee or 0)*sell_price)
        
        item_data = {
            'itemNumber': manage_number,
            'title': self.title,
            'productDescription': {
                'pc': '<a href="https://link.rakuten.co.jp/1/120/822/"><img src="https://image.rakuten.co.jp/angaroo/cabinet/shop_parts/08999148/imgrc0120857202.jpg" border="0"width="300" height="150"></a><br><a href="https://link.rakuten.co.jp/0/117/285/"><img src="https://image.rakuten.co.jp/angaroo/cabinet/shop_parts/08999135/imgrc0116834913.jpg" border="0"width="300" height="150"></a><br>',
                'sp': '<a href="https://link.rakuten.co.jp/1/120/822/"><img src="https://image.rakuten.co.jp/angaroo/cabinet/shop_parts/08999148/imgrc0120857202.jpg" border="0"width="300" height="150"></a><br><a href="https://link.rakuten.co.jp/0/117/285/"><img src="https://image.rakuten.co.jp/angaroo/cabinet/shop_parts/08999135/imgrc0116834913.jpg" border="0"width="300" height="150"></a><br>',
            },
            'itemType':  'NORMAL',
            'images': [{'type': 'CABINET', 'location': f'/{file_path}', 'alt': 'Image'} for file_path in success_images],
            'genreId': '214204',
            'features': {
                'displayManufacturerContents': True
            },
            # 'payment': {
            #     'taxRate': '0.08'
            # },
            'variants': {
                manage_number: {
                    'restockOnCancel': True,
                    'standardPrice': sell_price,
                    'articleNumber': {
                        'exemptionReason': 5
                    },
                    'shipping': {
                        'postageIncluded': True
                    }
                }
            }
        }
        resp = item_api.insert_item(manage_number=manage_number, data=item_data)

        # Register Inventory Stock
        if resp.status_code < 300:
            inventory_api = InventoryAPI(service_secret, license_key)
            inventory_data = {
                "mode": "ABSOLUTE",
                "quantity": self.quantity
            }
            resp = inventory_api.register_inventory_stock(manage_number=manage_number, variant_id=manage_number, data=inventory_data)
            
            self.manage_number = manage_number
            self.sell_price = sell_price
            self.shipping_fee = shipping_fee
            self.rakuten_fee = rakuten_fee
            self.point = 1
            self.profit = 500
            self.save()

            if resp.status_code < 300:
                self.status = self.Status.ACTIVE
                self.save()
                return 'success'
            else:
                return 'incomplete'
        else:
            return 'falied'

    @authenticated_users
    def has_read_permission(request):
        return True
    
    @authenticated_users
    def has_write_permission(request):
        return True


class ProductPhoto(models.Model):
    product = models.ForeignKey(
        "product.Product", null=True, blank=True, on_delete=models.SET_NULL
    )
    path = models.ImageField(
        _('image file'),
        upload_to="productphoto"
    )
    width = models.DecimalField(
        _('width'),
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )
    height = models.DecimalField(
        _('height'),
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )


class ProductSetting(models.Model):
    class RakutenFee(models.Choices):
        Zero = 0
        Eight = 8
        Ten = 10

    license_key = models.CharField(
        _("license Key"),
        max_length=255,
        null=True,
        blank=True,
    )
    service_secret = models.CharField(
        _("service Secret"),
        max_length=255,
        null=True,
        blank=True,
    )
    shipping_mail_fee = models.IntegerField(
        _("email Shipping Fee"),
        null=True,
        blank=True
    )
    shipping_60_fee = models.IntegerField(
        _("60 Shipping Fee"),
        null=True,
        blank=True
    )
    shipping_80_fee = models.IntegerField(
        _("80 Shipping Fee"),
        null=True,
        blank=True
    )
    shipping_100_fee = models.IntegerField(
        _("100 Shipping Fee"),
        null=True,
        blank=True
    )
    shipping_120_fee = models.IntegerField(
        _("120 Shipping Fee"),
        null=True,
        blank=True
    )
    scraping_update_amazon_from = models.IntegerField(
        _("upadating Amazon Time"),
        null=True,
        blank=True
    )
    scraping_update_tajimaya_from = models.IntegerField(
        _("updating Tajimaya Time"),
        null=True,
        blank=True
    )
    scraping_update_oroshi_from = models.IntegerField(
        _("updating Oroshi Time"),
        null=True,
        blank=True
    )
    rakuten_fee = models.IntegerField(
        _("rakuten Fee"),
        choices=RakutenFee.choices,
        default=RakutenFee.Ten
    )
    created_by = models.ForeignKey(
        "users.user",
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    @authenticated_users
    def has_read_permission(self):
        return True
    
    @authenticated_users
    def has_write_permission(self):
        return True
