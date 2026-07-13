import numpy
import pandas
import requests
from bs4 import BeautifulSoup


def test_imports():

    print("NumPy:", numpy.__version__)
    print("Pandas:", pandas.__version__)
    print("Requests OK")
    print("BeautifulSoup OK")


if __name__ == "__main__":
    test_imports()