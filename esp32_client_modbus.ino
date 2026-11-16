/*
  ESP32 -> convoyeur virtuel PC, via Modbus TCP.
  Bibliothèque Arduino : "modbus-esp8266" (compatible ESP32)
  Deux boutons entre GPIO et GND, résistances pull-up internes activées.
  GPIO 18 = MARCHE ; GPIO 19 = ARRÊT.
*/
#include <WiFi.h>
#include <ModbusIP_ESP8266.h>

const char* WIFI_SSID = "VOTRE_WIFI";
const char* WIFI_PASSWORD = "VOTRE_MOT_DE_PASSE";
IPAddress pc(192, 168, 1, 50); // A adapter à l'adresse IPv4 du PC
const uint16_t MODBUS_PORT = 1502;
const int BTN_MARCHE = 18;
const int BTN_ARRET = 19;

ModbusIP mb;
uint16_t nbCartons = 0;
bool ancienMarche = HIGH;
bool ancienArret = HIGH;
uint32_t derniereConnexion = 0;
uint32_t derniereLecture = 0;
uint32_t dernierBouton = 0;

bool apresEcriture(Modbus::ResultCode event, uint16_t transactionId, void* data) {
  if (event == Modbus::EX_SUCCESS) Serial.println("Commande Modbus acceptee");
  else Serial.printf("Erreur Modbus, code : %d\n", event);
  return true;
}

bool apresLecture(Modbus::ResultCode event, uint16_t transactionId, void* data) {
  if (event == Modbus::EX_SUCCESS) {
    Serial.printf("Cartons produits : %u\n", nbCartons);
  } else {
    Serial.printf("Erreur lecture : %d\n", event);
  }
  return true;
}

void setup() {
  Serial.begin(115200);
  pinMode(BTN_MARCHE, INPUT_PULLUP);
  pinMode(BTN_ARRET, INPUT_PULLUP);

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print('.');
  }
  Serial.print("\nIP ESP32 : ");
  Serial.println(WiFi.localIP());
  mb.client();
}

void loop() {
  mb.task();
  const uint32_t maintenant = millis();
  if (!mb.isConnected(pc) && maintenant - derniereConnexion >= 2000) {
    derniereConnexion = maintenant;
    mb.connect(pc, MODBUS_PORT);
  }

  const bool marche = digitalRead(BTN_MARCHE);
  const bool arret = digitalRead(BTN_ARRET);
  if (mb.isConnected(pc) && maintenant - dernierBouton >= 120) {
    // La commande ARRÊT est prioritaire.
    if (!arret && ancienArret) {
      dernierBouton = maintenant;
      mb.writeCoil(pc, 0, false, apresEcriture);
    } else if (!marche && ancienMarche) {
      dernierBouton = maintenant;
      mb.writeCoil(pc, 0, true, apresEcriture);
    }
  }
  ancienMarche = marche;
  ancienArret = arret;

  if (mb.isConnected(pc) && maintenant - derniereLecture >= 2000) {
    derniereLecture = maintenant;
    mb.readIreg(pc, 0, &nbCartons, 1, apresLecture);
  }
  delay(5);
}
