"""Interactive shell for the local embedding category experiment."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from semantic_categories import (
    EmbeddedExample,
    fit_logistic_category_model,
    predict_logistic_category,
    suggest_category,
)

MODEL = "nomic-embed-text"
OLLAMA_EMBED_URL = "http://127.0.0.1:11434/api/embed"

HISTORY = [
("UBER *TRIP HELP.UBER.COMCA", "Expenses:Transportation:Rides"),
("UBER *TRIP HELP.UBER.COM 800-5928996 CA", "Expenses:Transportation:Rides"),
("GEICO *AUTO 800-841-3000 DC", "Expenses:Auto:Insurance"),
("OPENAI *CHATGPT SUBSCR OPENAI.COM CA", "Expenses:Subscriptions"),
("AMAZON MKTPL*7A9N386E3 Amzn.com/billWA", "Expenses:Shopping:Online"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("ALBERTSONS LLC PAYROLL 260103 20979606 JOSLEYN,RANDY", "Income:Albertsons"),
("SQ *12TH FRET MUSIC Boise ID", "Expenses:Business Services"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("UNITED AIR 0162363806794PAYPAL COM TX", "Expenses:Transportation:Flights"),
("UNITED AIR 0162363806793PAYPAL COM TX", "Expenses:Transportation:Flights"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("Wikimedia 877-6009454 CA", "Expenses:Gifts and Donations"),
("ALBERTSONS LLC PAYROLL 260110 20979606 JOSLEYN,RANDY", "Income:Albertsons"),
("CHECK # 281", "Expenses:Government Fees"),
("UBER *TRIP HELP.UBER.COMCA", "Expenses:Transportation:Rides"),
("UBER *TRIP HELP.UBER.COMCA", "Expenses:Transportation:Rides"),
("ALBERTSONS #0162 BOISE ID", "Expenses:Shopping:Groceries"),
("BITTERCREEKRED FEATHER L BOISE ID", "Expenses:Eating Out"),
("WELLS FARGO REWARDS", "Income:Wells Fargo Rewards"),
("ALBERTSONS LLC PAYROLL 260117 20979606 JOSLEYN,RANDY", "Income:Albertsons"),
("STINKER # 107 BOISE ID", "Expenses:Auto:Gas"),
("ALBERTSONS LLC PAYROLL 260124 20979606 JOSLEYN,RANDY", "Income:Albertsons"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("WM SUPERCENTER #2508 BOISE ID", "Expenses:Shopping:Groceries"),
("OPENAI *CHATGPT SUBSCR OPENAI.COM CA", "Expenses:Subscriptions"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("ALBERTSONS LLC PAYROLL 260131 20979606 JOSLEYN,RANDY", "Income:Albertsons"),
("WHOLEFDS BOI #10284 BOISE ID", "Expenses:Shopping:Groceries"),
("GOOGLE *Mullvad VPN 855-836-3987 CA", "Expenses:Subscriptions"),
("PAYPAL *EBAY US 786-762-515 CA", "Expenses:Shopping:Online"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("ALBERTSONS LLC PAYROLL 260207 20979606 JOSLEYN,RANDY", "Income:Albertsons"),
("ADA COUNTY ASSESSOR DMV 888-8916064 ID", "Expenses:Government Fees"),
("Wikimedia 877-6009454 CA", "Expenses:Gifts and Donations"),
("Interest accrual", "Expenses:Interest"),
("THAT PLACE LLC BOISE ID", "Expenses:Eating Out"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("WELLS FARGO REWARDS", "Income:Wells Fargo Rewards"),
("ALBERTSONS LLC PAYROLL 260214 20979606 JOSLEYN,RANDY", "Income:Albertsons"),
("STANDARD RESTAURANT BOISEBOISE ID", "Expenses:Shopping:In-Store"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Shopping:Groceries"),
("THECUT INC* 4O8IXNSW 120-26811638 ID", "Expenses:Health:Grooming"),
("AMAZON MKTPL*B99JF3SS2 Amzn.com/billWA", "Expenses:Shopping:Online"),
("AMAZON MKTPL*B95BK92B2 Amzn.com/billWA", "Expenses:Shopping:Online"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("ALBERTSONS #0193 BOISE ID", "Expenses:Shopping:Groceries"),
("STINKER # 107 BOISE ID", "Expenses:Auto:Gas"),
("Interest accrual", "Expenses:Interest"),
("ALBERTSONS LLC PAYROLL 260221 20979606 JOSLEYN,RANDY", "Income:Albertsons"),
("AMAZON RETA* B180F6W20 WWW.AMAZON.COWA", "Expenses:Shopping:Online"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("AMAZON MKTPL*B96OJ27E1 Amzn.com/billWA", "Expenses:Shopping:Online"),
("Amazon.com*B91AB3BY0 Amzn.com/billWA", "Expenses:Shopping:Online"),
("AMAZON MKTPL*B991B2H50 Amzn.com/billWA", "Expenses:Shopping:Online"),
("AMAZON MKTPL*BE9TS4L81 Amzn.com/billWA", "Expenses:Shopping:Online"),
("AMAZON MKTPL*B99EA0QK0 Amzn.com/billWA", "Expenses:Shopping:Online"),
("AMAZON MKTPL*B93F99DX0 Amzn.com/billWA", "Expenses:Shopping:Online"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Shopping:Groceries"),
("STANDARD RESTAURANT BOISEBOISE ID", "Expenses:Shopping:In-Store"),
("Subway 1414 Boise ID", "Expenses:Eating Out"),
("OPENAI *CHATGPT SUBSCR OPENAI.COM CA", "Expenses:Subscriptions"),
("AMAZON MKTPL*B99K949R0 Amzn.com/billWA", "Expenses:Shopping:Online"),
("Capital Asian Market", "Expenses:Shopping:Groceries"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Shopping:Groceries"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Shopping:Groceries"),
("PAYPAL *BOISESTATEU BOISE402-935-7733 ID", "Expenses:Gifts and Donations"),
("ALBERTSONS #0193 BOISE ID", "Expenses:Shopping:Groceries"),
("AMAZON MKTPL*BE23E5GR1 Amzn.com/billWA", "Expenses:Shopping:Online"),
("ALBERTSONS LLC PAYROLL 260228 20979606 JOSLEYN,RANDY", "Income:Albertsons"),
("WALMART.COM 800-925-6278 AR", "Expenses:Shopping:Groceries"),
("CHEFSTORE 7564 BOISE ID", "Expenses:Shopping:Groceries"),
("AMAZON MKTPL*BE4PA1QI1 Amzn.com/billWA", "Expenses:Shopping:Online"),
("AMAZON MKTPL*BE20F6H71 Amzn.com/billWA", "Expenses:Shopping:Online"),
("UEP*MALA HOUSE BOISE ID", "Expenses:Eating Out"),
("Capital Asian Market", "Expenses:Shopping:Groceries"),
("Interest accrual", "Expenses:Interest"),
("ALBERTSONS #0193 BOISE ID", "Expenses:Shopping:Groceries"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Shopping:Groceries"),
("ALBERTSONS LLC PAYROLL 260307 20979606 JOSLEYN,RANDY", "Income:Albertsons"),
("AMAZON MKTPL*BP9TA8360 Amzn.com/billWA", "Expenses:Shopping:Online"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Shopping:Groceries"),
("TST*RED BENCH PIZZA Boise ID", "Expenses:Eating Out"),
("Wikimedia 877-6009454 CA", "Expenses:Gifts and Donations"),
("WAL-MART #2508 BOISE ID", "Expenses:Shopping:Groceries"),
("AMAZON MKTPL*BD4536F31 Amzn.com/billWA", "Expenses:Shopping:Online"),
("LOWES #00688* BOISE ID", "Expenses:Shopping:In-Store"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("PURCHASE AUTHORIZED ON 03/16 WINCO FOODS #1 WINCO110 E BOISE ID P586076050895213 CARD 4770", "Expenses:Shopping:Groceries"),
("ALBERTSONS LLC PAYROLL 260314 20979606 JOSLEYN,RANDY", "Income:Albertsons"),
("CHEFSTORE 7564 BOISE ID", "Expenses:Shopping:Groceries"),
("Capital Asian Market", "Expenses:Shopping:Groceries"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("WELLS FARGO REWARDS", "Income:Wells Fargo Rewards"),
("INTEREST PAYMENT", "Income:Savings interest"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("ALBERTSONS LLC PAYROLL 260321 20979606 JOSLEYN,RANDY", "Income:Albertsons"),
("SUBWAY 21812 BOISE ID", "Expenses:Eating Out"),
("Caffeina - Overland BOISE ID", "Expenses:Shopping:Groceries"),
("TST*THE WYLD CHILD Boise ID", "Expenses:Eating Out"),
("SQ *THE STIL Boise ID", "Expenses:Eating Out"),
("SQ *TACOS EL CHAVO BOISE ID", "Expenses:Eating Out"),
("DICE.FM 121-25747999 NY", "Expenses:Entertainment"),
("SQ *GENKI TAKOYAKI Boise ID", "Expenses:Eating Out"),
("SQ *NECKAR COFFEE BOISE ID", "Expenses:Eating Out"),
("SQ *THE RUSTY DOG Buhl ID", "Expenses:Eating Out"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Eating Out"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Shopping:Groceries"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Shopping:Groceries"),
("COSTCO GAS #0761 BOISE ID", "Expenses:Auto:Gas"),
("TREEFORT MUSIC FEST BOISE ID", "Expenses:Entertainment"),
("TREEFORT MUSIC FEST BOISE ID", "Expenses:Entertainment"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("ALBERTSONS LLC PAYROLL 260328 20979606 JOSLEYN,RANDY", "Income:Albertsons"),
("SQ *URBAN FOX COFFEE & BOBoise ID", "Expenses:Eating Out"),
("FRED-MEYER #0613 BOISE ID", "Expenses:Shopping:Groceries"),
("OPENAI *CHATGPT SUBSCR OPENAI.COM CA", "Expenses:Subscriptions"),
("ALBERTSONS #0193 BOISE ID", "Expenses:Shopping:Groceries"),
("SQ *MOUNTAIN TIMBER COFFEBoise ID", "Expenses:Eating Out"),
("PURCHASE AUTHORIZED ON 04/04 WINCO FOODS #1 WINCO110 E BOISE ID P306095100672893 CARD 4770", "Expenses:Shopping:Groceries"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("ALBERTSONS LLC PAYROLL 260404 20979606 JOSLEYN,RANDY", "Income:Albertsons"),
("FRED-MEYER #0613 BOISE ID", "Expenses:Shopping:Groceries"),
("ALBERTSONS LLC   PAYROLL    260404 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("WAL-MART #2508 BOISE ID", "Expenses:Shopping:Groceries"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Eating Out"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Shopping:Groceries"),
("SQ *PEEPERS CHILDRENS CLOBoise ID", "Expenses:Shopping:In-Store"),
("IDAHO CREPE COMPANY CHESTNAMPA ID", "Expenses:Eating Out"),
("AMAZON MKTPL*B73BV0EO1 Amzn.com/billWA", "Expenses:Shopping:Online"),
("SQ *12TH FRET MUSIC Boise ID", "Expenses:Business Services"),
("SQ *BOISE BOBA DOWN TOWN Boise ID", "Expenses:Eating Out"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("Wikimedia 877-6009454 CA", "Expenses:Gifts and Donations"),
("PAYPAL *GITHUB INC 402-935-7733 CA", "Expenses:Subscriptions"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("Capital Asian Market", "Expenses:Shopping:Groceries"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("Interest accrual", "Expenses:Interest"),
("ALBERTSONS LLC PAYROLL 260411 20979606 JOSLEYN,RANDY", "Income:Albertsons"),
("WM SUPERCENTER #2508 BOISE ID", "Expenses:Shopping:Groceries"),
("ALBERTSONS LLC   PAYROLL    260411 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("SQ *THE STIL Boise ID", "Expenses:Eating Out"),
("ALBERTSONS #0193 BOISE ID", "Expenses:Shopping:Groceries"),
("SQ *SEOUL STREET CAFE Boise ID", "Expenses:Eating Out"),
("SQ *TACOS EL CHAVO BOISE ID", "Expenses:Eating Out"),
("Idaho Mountain Touring BOISE ID", "Expenses:Shopping:In-Store"),
("WELLS FARGO REWARDS", "Income:Wells Fargo Rewards"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Shopping:Groceries"),
("PURCHASE AUTHORIZED ON 04/21 WINCO FOODS #1 WINCO110 E BOISE ID P356112053040279 CARD 4770", "Expenses:Shopping:Groceries"),
("PURCHASE                                AUTHORIZED ON   04/21 WINCO FOODS #1 WINCO110 E BOISE         ID  P356112053040279   CARD 4770", "Expenses:Shopping:Groceries"),
("ALBERTSONS LLC PAYROLL 260418 20979606 JOSLEYN,RANDY", "Income:Albertsons"),
("ALBERTSONS LLC   PAYROLL    260418 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("Interest accrual", "Expenses:Interest"),
("WM SUPERCENTER #2508 BOISE ID", "Expenses:Shopping:Groceries"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Shopping:Groceries"),
("ALBERTSONS #0162 BOISE ID", "Expenses:Shopping:Groceries"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Eating Out"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Shopping:Groceries"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("ALBERTSONS LLC   PAYROLL    260425 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("TST*RED BENCH PIZZA Boise ID", "Expenses:Eating Out"),
("UEP*MALA HOUSE BOISE ID", "Expenses:Eating Out"),
("Capital Asian Market", "Expenses:Shopping:Groceries"),
("SLICK ROCK COFFEE CO 178-15833699 ID", "Expenses:Eating Out"),
("ALBERTSONS #0193 BOISE ID", "Expenses:Shopping:Groceries"),
("OPENAI *CHATGPT SUBSCR OPENAI.COM CA", "Expenses:Subscriptions"),
("Interest accrual", "Expenses:Interest"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("PURCHASE                                AUTHORIZED ON   05/06 WINCO FOODS #1 WINCO110 E BOISE         ID  P586126845823903   CARD 4770", "Expenses:Shopping:Groceries"),
("ALBERTSONS LLC   PAYROLL    260502 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("PAYPAL *GITHUB INC 402-935-7733 CA", "Expenses:Subscriptions"),
("Google Mullvad VPN 650-2530000 CA", "Expenses:Subscriptions"),
("SQ *URBAN FOX COFFEE & BOBoise ID", "Expenses:Eating Out"),
("ADACOSHERIFF2083320102 BOISE ID", "Expenses:Government Fees"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Shopping:Groceries"),
("COSTCO GAS #0761 BOISE ID", "Expenses:Auto:Gas"),
("Caffeina - Overland BOISE ID", "Expenses:Shopping:Groceries"),
("ALBERTSONS #0193 BOISE ID", "Expenses:Shopping:Groceries"),
("LS GEORGES CYCLES 120-83433782 ID", "Expenses:Shopping:In-Store"),
("Capital Asian Market", "Expenses:Shopping:Groceries"),
("ALBERTSONS #0193 BOISE ID", "Expenses:Shopping:Groceries"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("Costco", "Expenses:Eating Out"),
("Wikimedia 877-6009454 CA", "Expenses:Gifts and Donations"),
("ALBERTSONS LLC   PAYROLL    260509 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("SQ *NEIGHBOR TIM?S BBQ & Boise ID", "Expenses:Eating Out"),
("TST*JUST CHICKEN - BOISE Boise ID", "Expenses:Eating Out"),
("Capital Asian Market", "Expenses:Shopping:Groceries"),
("PURCHASE                                AUTHORIZED ON   05/17 WINCO FOODS #1 WINCO110 E BOISE         ID  P586138014823708   CARD 4770", "Expenses:Shopping:Groceries"),
("SQ *URBAN FOX COFFEE & BOBoise ID", "Expenses:Eating Out"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("ALBERTSONS LLC   PAYROLL    260516 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("WELLS FARGO REWARDS", "Income:Wells Fargo Rewards"),
("PP*SPOTIFY*P42C3EDA90 203-318-9708 NY", "Expenses:Subscriptions"),
("Capital Asian Market", "Expenses:Shopping:Groceries"),
("BURGER KING #12310 Q07 BOISE ID", "Expenses:Eating Out"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Shopping:Groceries"),
("TST* EUREKA RESTAURANT GRBOISE ID", "Expenses:Eating Out"),
("LOWES #00688* BOISE ID", "Expenses:Shopping:In-Store"),
("PURCHASE                                AUTHORIZED ON   05/23 WINCO FOODS #6 WINCO8200  BOISE         ID  P586143663948371   CARD 4770", "Expenses:Shopping:Groceries"),
("AMAZON RETA* LF1PU7J23 WWW.AMAZON.COWA", "Expenses:Shopping:Online"),
("AMAZON MKTPL*UJ8RX6WA3 Amzn.com/billWA", "Expenses:Shopping:Online"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("ALBERTSONS LLC   PAYROLL    260523 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("PURCHASE                                AUTHORIZED ON   05/28 ADACOSHERIFF208332        BOISE         ID  S356148819160719   CARD 0199", "Expenses:Government Fees"),
("PAYPAL *EBAY US 402-935-7733 CA", "Expenses:Shopping:Online"),
("ALBERTSONS #0193 BOISE ID", "Expenses:Shopping:Groceries"),
("Etsy.com*FringeAccessorie718-8557955 NY", "Expenses:Gifts and Donations"),
("LS GEORGES CYCLES 120-83433782 ID", "Expenses:Shopping:In-Store"),
("ATM WITHDRAWAL                 AUTHORIZED ON   05/30 1205 S BROADWAY AVE       BOISE         ID  0007746           ATM ID 4502F    CARD 4770", "Expenses:Cash"),
("PURCHASE                                AUTHORIZED ON   05/30 WINCO FOODS #1 WINCO110 E BOISE         ID  P586150709515321   CARD 4770", "Expenses:Shopping:Groceries"),
("ALPENHAUS BOISE ID", "Expenses:Eating Out"),
("ALPENHAUS BOISE ID", "Expenses:Eating Out"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Shopping:Groceries"),
("OPENAI *CHATGPT SUBSCR OPENAI.COM CA", "Expenses:Subscriptions"),
("ALBERTSONS LLC   PAYROLL    260530 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("ALBERTSONS #0193 BOISE ID", "Expenses:Shopping:Groceries"),
("SQ *CHINGU KOREAN EATS Boise ID", "Expenses:Eating Out"),
("Capital Asian Market", "Expenses:Shopping:Groceries"),
("WinCo", "Expenses:Shopping:Groceries"),
("SQ *THE STIL Boise ID", "Expenses:Eating Out"),
("SQ *THE STIL Boise ID", "Expenses:Eating Out"),
("Etsy.com*AllysAtticUS 718-8557955 NY", "Expenses:Gifts and Donations"),
("PURCHASE                                AUTHORIZED ON   06/06 WINCO FOODS #1 WINCO110 E BOISE         ID  P586157647454558   CARD 4770", "Expenses:Shopping:Groceries"),
("PAYPAL *GITHUB INC 402-935-7733 CA", "Expenses:Subscriptions"),
("ALBERTSONS #0199 BOISE ID", "Expenses:Shopping:Groceries"),
("TST*RED BENCH PIZZA Boise ID", "Expenses:Eating Out"),
("BIG SMOKE 128 BOISE ID", "Expenses:Gifts and Donations"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("AMAZON MKTPL*9K44G4N23 Amzn.com/billWA", "Expenses:Shopping:Online"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Shopping:Groceries"),
("COSTCO GAS #0761 BOISE ID", "Expenses:Auto:Gas"),
("WP*Driving Tester Boise ID", "Expenses:Government Fees"),
("FRED-MEYER #0613 BOISE ID", "Expenses:Shopping:In-Store"),
("ROSS STORES #1125 BOISE ID", "Expenses:Shopping:In-Store"),
("KFC C750060 BOISE ID", "Expenses:Eating Out"),
("ALBERTSONS LLC   PAYROLL    260606 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("ALBERTSONS #0193 BOISE ID", "Expenses:Shopping:Groceries"),
("Wikimedia 877-6009454 CA", "Expenses:Gifts and Donations"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("PURCHASE                                AUTHORIZED ON   06/15 WINCO FOODS #1 WINCO110 E BOISE         ID  P386166844474583   CARD 4770", "Expenses:Shopping:Groceries"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("ARBYS 7311 BOISE ID", "Expenses:Eating Out"),
("WAL-MART #3094 BOISE ID", "Expenses:Shopping:Groceries"),
("McDonald's", "Expenses:Eating Out"),
("AMAZON MKTPL*J02FS4C93 Amzn.com/billWA", "Expenses:Shopping:Online"),
("AMAZON MKTPL*2J0GC1J13 Amzn.com/billWA", "Expenses:Shopping:Online"),
("SQ *URBAN FOX COFFEE & BOBoise ID", "Expenses:Eating Out"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("Capital Asian Market", "Expenses:Shopping:Groceries"),
("ALBERTSONS LLC   PAYROLL    260613 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("BURGER KING #10956 Q07 BOISE ID", "Expenses:Eating Out"),
("WELLS FARGO REWARDS", "Income:Wells Fargo Rewards"),
("PURCHASE                                AUTHORIZED ON   06/19 THANAS LITTLE WORL        BOISE         ID  S466170610006841   CARD 0199", "Expenses:Shopping:Groceries"),
("WM SUPERCENTER #3094 BOISE ID", "Expenses:Shopping:Groceries"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("INTEREST PAYMENT", "Income:Savings interest"),
("ALBERTSONS LLC   PAYROLL    260620 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("AMAZON MKTPL*HK6OS2ME3 Amzn.com/billWA", "Expenses:Shopping:Online"),
("TST*RED BENCH PIZZA Boise ID", "Expenses:Eating Out"),
("SQ *SEOUL STREET CAFE Boise ID", "Expenses:Eating Out"),
("SQ *CUPBOP BOISE Boise ID", "Expenses:Eating Out"),
("AMAZON MKTPL*QU4CM8C63 Amzn.com/billWA", "Expenses:Shopping:Online"),
("AMAZON MKTPL*O87PC5WJ3 Amzn.com/billWA", "Expenses:Shopping:Online"),
("AMAZON MKTPL*LL1TT3RM3 Amzn.com/billWA", "Expenses:Shopping:Online"),
("AMAZON MKTPL*IP0A11JL3 Amzn.com/billWA", "Expenses:Shopping:Online"),
("Capital Asian Market", "Expenses:Shopping:Groceries"),
("GEICO *AUTO 800-841-3000 DC", "Expenses:Auto:Insurance"),
("ALBERTSONS LLC   PAYROLL    260627 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("TJMAXX #0415 BOISE ID", "Expenses:Shopping:In-Store"),
("OPENAI *CHATGPT SUBSCR OPENAI.COM CA", "Expenses:Subscriptions"),
("ALBERTSONS #0193 BOISE ID", "Expenses:Shopping:Groceries"),
("ALBERTSONS #0193 BOISE ID", "Expenses:Shopping:Groceries"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Shopping:Groceries"),
("AMAZON MKTPL*ND3CG08B3 Amzn.com/billWA", "Expenses:Shopping:Online"),
("AMAZON MKTPL*IW2RW0GB3 Amzn.com/billWA", "Expenses:Shopping:Online"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("PAYPAL *GITHUB INC 402-935-7733 CA", "Expenses:Subscriptions"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("ALBERTSONS LLC   PAYROLL    260704 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("McDonald's", "Expenses:Eating Out"),
("Capital Asian Market", "Expenses:Shopping:Groceries"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("Wikimedia 877-6009454 CA", "Expenses:Gifts and Donations"),
("AMAZON MKTPL*L56339393 Amzn.com/billWA", "Expenses:Shopping:Online"),
("AMAZON MKTPL*U40X99M53 Amzn.com/billWA", "Expenses:Shopping:Online"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Shopping:Groceries"),
("COSTCO GAS #0761 BOISE ID", "Expenses:Auto:Gas"),
("ALBERTSONS LLC   PAYROLL    260711 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("AMAZON RETA* II77P9WH3 WWW.AMAZON.COWA", "Expenses:Shopping:Online"),
("AMAZON RETA* Y024C1YJ3 WWW.AMAZON.COWA", "Expenses:Shopping:Online"),
("WELLS FARGO REWARDS", "Income:Wells Fargo Rewards"),
("PURCHASE                                AUTHORIZED ON   07/21 WINCO FOODS #1 110 E MYRT BOISE         ID  P346202831097710   CARD 4770", "Expenses:Shopping:Groceries"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("ALBERTSONS LLC   PAYROLL    260718 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("THECARPARK PARKMOBILE APP208-3366597 ID", "Expenses:Transportation"),
("PP*SPOTIFY*P44E7DAF16 402-935-7733 NY", "Expenses:Subscriptions"),
("PURCHASE                                AUTHORIZED ON   07/24 TJMAXX #0415              BOISE         ID  P000000442270293   CARD 0199", "Expenses:Shopping:In-Store"),
("Capital Asian Market", "Expenses:Shopping:Groceries"),
("AL'S SPORTING GOODS - BOIBOISE ID", "Expenses:Shopping:In-Store"),
("PURCHASE                                AUTHORIZED ON   07/24 ROSS STORES #217          BOISE         ID  S306205627757385   CARD 0199", "Expenses:Shopping:In-Store"),
("PURCHASE                                AUTHORIZED ON   07/25 COSTCO WHSE #0761         BOISE         ID  P586206650985792   CARD 0199", "Expenses:Shopping:Groceries"),
("PURCHASE                                AUTHORIZED ON   07/25 COSTCO WHSE #0761         BOISE         ID  P356206652501666   CARD 0199", "Expenses:Shopping:Groceries"),
("PURCHASE                                AUTHORIZED ON   07/25 WM SUPERCENTER #2508      BOISE         ID  P000000355001696   CARD 0199", "Expenses:Shopping:Groceries"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("PURCHASE RETURN                         AUTHORIZED ON   07/26 TJMAXX #0415              BOISE         ID  S466207620101274   CARD 0199", "Expenses:Shopping:In-Store"),
("AMAZON RETA* BJ3UF01L3 WWW.AMAZON.COWA", "Expenses:Shopping:Online"),
("ALBERTSONS LLC   PAYROLL    260725 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("PURCHASE                                AUTHORIZED ON   07/29 TJMAXX #0415              BOISE         ID  P000000852628100   CARD 0199", "Expenses:Shopping:In-Store"),
("PURCHASE                                AUTHORIZED ON   07/29 WM SUPERCENTER #2508      BOISE         ID  P000000155545497   CARD 0199", "Expenses:Shopping:Groceries"),
("NAHM THAI AND BURMESE CU BOISE ID", "Expenses:Eating Out"),
("ALBERTSONS #0193 BOISE ID", "Expenses:Shopping:Groceries"),
("OPENAI *CHATGPT SUBSCR OPENAI.COM CA", "Expenses:Subscriptions"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("PURCHASE                                AUTHORIZED ON   08/01 FRED-MEYER #0662          BOISE         ID  P000000145039240   CARD 0199", "Expenses:Shopping:Groceries"),
("Capital Asian Market", "Expenses:Shopping:Groceries"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("NEW LEAF DENTAL MERIDIAN ID", "Expenses:Health"),
("GOOGLE *MULLVAD VPN 888-986-7944 CA", "Expenses:Subscriptions"),
("MARSHALLS #871 MERIDIAN ID", "Expenses:Shopping:In-Store"),
("TST*AUBERGINE KITCHEN - Meridian ID", "Expenses:Eating Out"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("ALBERTSONS LLC   PAYROLL    260801 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("PURCHASE                                AUTHORIZED ON   08/07 WM SUPERCENTER #2508      BOISE         ID  P000000640054560   CARD 0199", "Expenses:Shopping:Groceries"),
("SQ *AUNTIE JUNE'S JAMROCKBoise ID", "Expenses:Eating Out"),
("SQ *CREPE JOY Boise ID", "Expenses:Eating Out"),
("PURCHASE                                AUTHORIZED ON   08/09 COSTCO WHSE #0761         BOISE         ID  P356221669582993   CARD 0199", "Expenses:Shopping:Groceries"),
("PURCHASE                                AUTHORIZED ON   08/09 WM SUPERCENTER #2508      BOISE         ID  P000000251516517   CARD 0199", "Expenses:Shopping:Groceries"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("ALBERTSONS LLC   PAYROLL    260808 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("HAWKINS PAC OUT 208-3389627 ID", "Expenses:Eating Out"),
("Wikimedia 877-6009454 CA", "Expenses:Gifts and Donations"),
("AMAZON RETA* 5A4HN0JB0 WWW.AMAZON.COWA", "Expenses:Shopping:Online"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("Capital Asian Market", "Expenses:Shopping:Groceries"),
("PURCHASE                                AUTHORIZED ON   08/15 WINCO FOODS #6 8200 FAIRV BOISE         ID  P356228035673580   CARD 0199", "Expenses:Shopping:Groceries"),
("WM SUPERCENTER #2508 BOISE ID", "Expenses:Shopping:Groceries"),
("COSTCO GAS #0761 BOISE ID", "Expenses:Auto:Gas"),
("COSTCO WHSE #0761 BOISE ID", "Expenses:Shopping:Groceries"),
("PAYPAL *SECONDIPITY SECON402-935-7733 MD", "Expenses:Shopping:Online"),
("ALBERTSONS LLC   PAYROLL    260815 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("PURCHASE                                AUTHORIZED ON   08/21 TJMAXX #0415              BOISE         ID  P000000744316860   CARD 0199", "Expenses:Shopping:In-Store"),
("PP*SPOTIFY*P4604C040E 402-935-7733 NY", "Expenses:Subscriptions"),
("AMAZON MKTPL*5O0QH3JU0 Amzn.com/billWA", "Expenses:Shopping:Online"),
("WELLS FARGO REWARDS", "Income:Wells Fargo Rewards"),
("McDonald's", "Expenses:Eating Out"),
("PURCHASE                                AUTHORIZED ON   08/21 SCHNITZEL GARTEN          EAGLE         ID  S346234052774851   CARD 0199", "Expenses:Unknown"),
("FRED-MEYER #0613 BOISE ID", "Expenses:Unknown"),
("SQ *URBAN FOX COFFEE & BOBoise ID", "Expenses:Eating Out"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("INTEREST PAYMENT", "Expenses:Unknown"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("ALBERTSONS LLC   PAYROLL    260822 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("SUBWAY 13638 BOISE ID", "Expenses:Unknown"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("PURCHASE                                AUTHORIZED ON   08/28 MACY'S      393 370 N MIL BOISE         ID  P466240751967986   CARD 0199", "Expenses:Unknown"),
("PACIFIC CREST-KIOSK 3 CALDWELL ID", "Expenses:Unknown"),
("BUTLER AMUSEMENTS INC BEAVERTON OR", "Expenses:Unknown"),
("BUTLER AMUSEMENTS INC BEAVERTON OR", "Expenses:Unknown"),
("ADA COUNTY EXPO IDAH 800-514-3849 ID", "Expenses:Unknown"),
("ELEPHANT EARS RIDGEFIELD WA", "Expenses:Unknown"),
("IHOP 1751 BOISE ID", "Expenses:Unknown"),
("SQ *BLUE FEATHER BAKERY Lindon UT", "Expenses:Unknown"),
("SQ *BROKENBOW LLC DBA PARHighland UT", "Expenses:Unknown"),
("ONLINE PAYMENT THANK YOU", "Expenses:Unknown"),
("ALBERTSONS #0193 BOISE ID", "Expenses:Shopping:Groceries"),
("PURCHASE                                AUTHORIZED ON   08/28 ROSS STORES #217          BOISE         ID  S306240732913697   CARD 0199", "Expenses:Unknown"),
("PURCHASE                                AUTHORIZED ON   08/28 JCPENNEY 2312             BOISE         ID  S386240782504692   CARD 0199", "Expenses:Unknown"),
("ONLINE TRANSFER REF #IB0ZKLYZNB TO WELLS FARGO AUTOGRAPH VISA CARD XXXXXXXXXXXX9867 ON 08/29/26", "Expenses:Unknown"),
("ATM WITHDRAWAL                 AUTHORIZED ON   08/31 5161 W Overland Road      Boise         ID  0000493           ATM ID 7541D    CARD 0199", "Expenses:Unknown"),
("PURCHASE                                AUTHORIZED ON   08/31 WM SUPERCENTER #2508      BOISE         ID  P000000145293107   CARD 0199", "Expenses:Shopping:Groceries"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),
("PURCHASE                                AUTHORIZED ON   09/01 THANAS LITTLE WORL        BOISE         ID  S466244611753366   CARD 0199", "Expenses:Unknown"),
("ALBERTSONS LLC   PAYROLL    260829 20979606        JOSLEYN,RANDY", "Income:Albertsons"),
("PURCHASE                                AUTHORIZED ON   09/03 WINCO FOODS #1 110 E MYRT BOISE         ID  P466247000350640   CARD 4770", "Expenses:Shopping:Groceries"),
("OPENAI *CHATGPT SUBSCR OPENAI.COM CA", "Expenses:Subscriptions"),
("TC @ ALBERTSONS CORPORAT BOISE ID", "Expenses:Eating Out"),

]

QUERIES = [
    "WINCO FOODS #004 debit card purchase",
    "CHEVRON 0204567 BOISE ID",
    "CITY OF BOISE PARKS & REC",
    "THE RECORD EXCHANGE",
    "AMZN MKTP US*Q72L1",
]


def embed(texts: list[str]) -> list[list[float]]:
    payload = json.dumps(
        {"model": MODEL, "input": [f"classification: {text}" for text in texts]}
    ).encode()
    request = urllib.request.Request(
        OLLAMA_EMBED_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)["embeddings"]


def clear() -> None:
    print("\033[2J\033[H", end="")


def main() -> None:
    try:
        usable_history = [
            (description, category)
            for description, category in HISTORY
            if not category.endswith(":Unknown")
        ]
        history_vectors = embed([description for description, _ in usable_history])
    except (OSError, urllib.error.URLError, KeyError) as error:
        raise SystemExit(
            f"Could not use Ollama model {MODEL!r}: {error}\n"
            "Start Ollama and ensure the model exists: ollama pull nomic-embed-text"
        ) from error

    examples = [
        EmbeddedExample(description, category, vector)
        for (description, category), vector in zip(usable_history, history_vectors, strict=True)
    ]
    base_example_count = len(examples)
    logistic_model = fit_logistic_category_model(examples)
    index = 0
    query = QUERIES[index]
    show_json = False
    learned: list[str] = []
    last_action = ""

    while True:
        query_vector = embed([query])[0]
        neighbor_result = suggest_category(query_vector, examples)
        logistic_result = predict_logistic_category(query_vector, logistic_model)
        candidate_categories = list(
            dict.fromkeys(
                [score.category for score in logistic_result.category_scores[:5]]
                + [score.category for score in neighbor_result.category_scores[:5]]
            )
        )[:9]
        clear()
        print("\033[1mSEMANTIC CATEGORY PROTOTYPE\033[0m")
        print("\033[2mOne embedding set, compared as logistic regression and nearest neighbors\033[0m\n")
        print(f"\033[1mImported text\033[0m  {query}")
        print(f"\033[1mLogistic result\033[0m {logistic_result.category}")
        print(f"\033[1mNeighbor result\033[0m {neighbor_result.category or 'No suggestion'}")
        print(f"\033[1mConfirmed now\033[0m  {len(learned)} examples")
        if last_action:
            print(f"\033[1mLast action\033[0m    {last_action}")
        print("\n\033[1mNearest categorized evidence\033[0m")
        for neighbor in neighbor_result.neighbors:
            print(f"  {neighbor.similarity:6.3f}  {neighbor.category:<29} {neighbor.description}")
        print("\n\033[1mLogistic regression ranking\033[0m")
        for score in logistic_result.category_scores[:5]:
            print(f"  {score.probability:6.1%}  {score.category}")
        print(
            f"  margin {logistic_result.margin:.1%} "
            "\033[2m(probabilities are comparative, not calibrated confidence)\033[0m"
        )
        print("\n\033[1mChoose the correct category to add as a confirmed example\033[0m")
        for choice, category in enumerate(candidate_categories, start=1):
            model_marks = []
            if category == logistic_result.category:
                model_marks.append("logistic")
            if category == neighbor_result.category:
                model_marks.append("neighbors")
            mark = f" \033[2m← {' + '.join(model_marks)}\033[0m" if model_marks else ""
            print(f"  \033[1m[{choice}]\033[0m {category}{mark}")
        if show_json:
            print("\n\033[1mFull state\033[0m")
            print(json.dumps({"query": query, "neighbors": asdict(neighbor_result), "logistic": asdict(logistic_result), "learned": learned}, indent=2))
        print("\n\033[1m[1-9]\033[0m confirm category  \033[1m[n]\033[0m next case  \033[1m[e]\033[0m edit text  \033[1m[j]\033[0m JSON  \033[1m[r]\033[0m reset  \033[1m[q]\033[0m quit")
        action = input("> ").strip().lower()
        if action == "q":
            return
        if action == "n":
            index = (index + 1) % len(QUERIES)
            query = QUERIES[index]
            last_action = ""
        elif action == "e":
            query = input("Statement description: ").strip() or query
            last_action = ""
        elif action == "j":
            show_json = not show_json
        elif action == "r":
            examples = examples[:base_example_count]
            logistic_model = fit_logistic_category_model(examples)
            learned.clear()
            last_action = "Cleared all confirmed examples"
        elif action.isdigit():
            choice = int(action) - 1
            if 0 <= choice < len(candidate_categories):
                selected_category = candidate_categories[choice]
                examples.append(EmbeddedExample(query, selected_category, query_vector))
                logistic_model = fit_logistic_category_model(examples)
                learned.append(f"{query} → {selected_category}")
                last_action = f"Confirmed {selected_category}"
            else:
                last_action = f"No category suggestion numbered {action}"


if __name__ == "__main__":
    main()
