from decimal import Decimal as D

from django.contrib.auth.models import User

from orders.models import ChatFile, Order, OrderLine, ParsedChatFile, Product


def make_user(username="seller"):
    return User.objects.create_user(username=username, password="x")


def make_parsed_file(user):
    chat = ChatFile.objects.create(user=user, filename="chat.txt", filepath="chatfile/chat.txt", filetype="text")
    return ParsedChatFile.objects.create(user=user, chatfile=chat, file_name="chat_processed.xlsx",
                                         processed_file_path="processedchatfile/chat_processed.xlsx")


def make_products():
    return (Product.objects.create(key="kesar_mango", name="Kesar Mango", price=D("120"), price_unit="kg"),
            Product.objects.create(key="lychee", name="Lychee", price=D("250"), price_unit="box"))


def add_line(order, product, quantity, unit, name=None, flags=None):
    line = OrderLine(order=order, product=product, name=name or (product.name if product else "Unknown"),
                     quantity=quantity, unit=unit, flags=list(flags or []))
    line.reprice()
    line.save()
    return line
