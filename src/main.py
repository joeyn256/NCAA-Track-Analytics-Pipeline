from scraper.scrape_roster import main as scrape_roster
from scraper.scrape_athletes import main as scrape_athletes



def main():

    print("Starting Running Analytics Pipeline")


    scrape_roster()


    scrape_athletes()


    print("Finished")


if __name__ == "__main__":
    main()