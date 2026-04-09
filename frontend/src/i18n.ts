/**
 * Internationalization (i18n) - French & English
 */

export type Locale = 'fr' | 'en';

const translations = {
  // ── Header ──
  'app.title': { en: 'RF Planner', fr: 'Planificateur RF' },
  'app.version': { en: 'v1.0', fr: 'v1.0' },
  'app.gpu': { en: 'GPU', fr: 'GPU' },
  'app.help': { en: 'Help', fr: 'Aide' },

  // ── Tabs ──
  'tab.tx': { en: 'Transmitter', fr: 'Transmetteur' },
  'tab.signal': { en: 'Signal', fr: 'Signal' },
  'tab.antenna': { en: 'Antenna', fr: 'Antenne' },
  'tab.rx': { en: 'Receiver', fr: 'Récepteur' },
  'tab.model': { en: 'Model', fr: 'Modèle' },
  'tab.env': { en: 'Environment', fr: 'Environnement' },
  'tab.output': { en: 'Output', fr: 'Sortie' },

  // ── Transmitter ──
  'tx.title': { en: 'Site / Transmitter', fr: 'Site / Transmetteur' },
  'tx.name': { en: 'Name', fr: 'Nom' },
  'tx.network': { en: 'Network', fr: 'Réseau' },
  'tx.coordinates': { en: 'Coordinates', fr: 'Coordonnées' },
  'tx.latitude': { en: 'Latitude', fr: 'Latitude' },
  'tx.longitude': { en: 'Longitude', fr: 'Longitude' },
  'tx.height': { en: 'Height', fr: 'Hauteur' },
  'tx.height_unit': { en: 'meters AGL', fr: 'mètres AGL' },

  // ── Signal ──
  'sig.title': { en: 'Signal', fr: 'Signal' },
  'sig.frequency': { en: 'Frequency', fr: 'Fréquence' },
  'sig.power': { en: 'RF Power', fr: 'Puissance RF' },
  'sig.bandwidth': { en: 'Bandwidth', fr: 'Largeur de bande' },
  'sig.erp': { en: 'ERP', fr: 'PAR' },
  'sig.eirp': { en: 'EIRP', fr: 'PIRE' },

  // ── Feeder ──
  'feed.title': { en: 'Feeder / Cable', fr: 'Câble / Connectique' },
  'feed.loss': { en: 'Total Loss', fr: 'Pertes totales' },
  'feed.efficiency': { en: 'Efficiency', fr: 'Efficacité' },

  // ── Antenna ──
  'ant.title': { en: 'Antenna', fr: 'Antenne' },
  'ant.pattern': { en: 'Pattern Type', fr: 'Type de diagramme' },
  'ant.gain': { en: 'Gain', fr: 'Gain' },
  'ant.azimuth': { en: 'Azimuth', fr: 'Azimut' },
  'ant.tilt': { en: 'Tilt', fr: 'Inclinaison' },
  'ant.h_beamwidth': { en: 'H. Beamwidth', fr: 'Ouverture H.' },
  'ant.v_beamwidth': { en: 'V. Beamwidth', fr: 'Ouverture V.' },
  'ant.polarization': { en: 'Polarization', fr: 'Polarisation' },
  'ant.pattern_dipole': { en: 'Half-Wave Dipole', fr: 'Dipôle demi-onde' },
  'ant.pattern_isotropic': { en: 'Isotropic', fr: 'Isotrope' },
  'ant.pattern_custom': { en: 'Custom', fr: 'Personnalisé' },
  'ant.pattern_sector': { en: 'Sector Panel', fr: 'Panneau sectoriel' },
  'ant.pattern_yagi': { en: 'Yagi', fr: 'Yagi' },

  // ── Receiver ──
  'rx.title': { en: 'Mobile / Receiver', fr: 'Mobile / Récepteur' },
  'rx.height': { en: 'Height', fr: 'Hauteur' },
  'rx.gain': { en: 'Receive Gain', fr: 'Gain réception' },
  'rx.units': { en: 'Measured Units', fr: 'Unités de mesure' },
  'rx.sensitivity': { en: 'Sensitivity', fr: 'Sensibilité' },
  'rx.unit_dbm': { en: 'Received Power (dBm)', fr: 'Puissance reçue (dBm)' },
  'rx.unit_snr': { en: 'Signal to Noise (dB)', fr: 'Rapport S/B (dB)' },
  'rx.unit_dbuv': { en: 'Field Strength (dBuV/m)', fr: 'Champ (dBuV/m)' },

  // ── Model ──
  'mdl.title': { en: 'Propagation Model', fr: 'Modèle de propagation' },
  'mdl.model': { en: 'Model', fr: 'Modèle' },
  'mdl.reliability': { en: 'Reliability', fr: 'Fiabilité' },
  'mdl.diffraction': { en: 'Diffraction', fr: 'Diffraction' },
  'mdl.diff_none': { en: 'None', fr: 'Aucune' },
  'mdl.diff_knife': { en: 'Single Knife Edge', fr: 'Lame simple' },
  'mdl.diff_bullington': { en: 'Bullington 77', fr: 'Bullington 77' },
  'mdl.diff_deygout': { en: 'Deygout 94', fr: 'Deygout 94' },

  // ── Environment ──
  'env.title': { en: 'Environment', fr: 'Environnement' },
  'env.elevation': { en: 'Elevation Model', fr: "Modèle d'élévation" },
  'env.elevation_dtm': { en: 'Terrain / DTM', fr: 'Terrain / MNT' },
  'env.elevation_dsm': { en: 'Surface / DSM', fr: 'Surface / MNS' },
  'env.landcover': { en: 'Land Cover', fr: 'Couvert terrestre' },
  'env.buildings': { en: 'Buildings', fr: 'Bâtiments' },
  'env.noise_floor': { en: 'Noise Floor', fr: 'Plancher de bruit' },
  'env.on': { en: 'ON', fr: 'ACTIF' },
  'env.off': { en: 'OFF', fr: 'INACTIF' },

  // ── Output ──
  'out.title': { en: 'Output', fr: 'Sortie' },
  'out.resolution': { en: 'Resolution', fr: 'Résolution' },
  'out.radius': { en: 'Radius', fr: 'Rayon' },
  'out.color_schema': { en: 'Color Schema', fr: 'Palette de couleurs' },
  'out.megapixels': { en: 'Megapixels', fr: 'Mégapixels' },

  // ── Actions ──
  'action.run': { en: 'Run Calculation', fr: 'Lancer le calcul' },
  'action.running': { en: 'Computing...', fr: 'Calcul en cours...' },
  'action.save_template': { en: 'Save Template', fr: 'Sauvegarder le modèle' },
  'action.clear': { en: 'Clear', fr: 'Effacer' },

  // ── Console ──
  'console.title': { en: 'Console', fr: 'Console' },
  'console.ready': { en: 'RF Planner ready.', fr: 'Planificateur RF prêt.' },
  'console.calculation_start': { en: 'Starting area coverage calculation...', fr: 'Démarrage du calcul de couverture...' },
  'console.calculation_done': { en: 'Calculation complete', fr: 'Calcul terminé' },
  'console.error': { en: 'ERROR', fr: 'ERREUR' },
  'console.tx_moved': { en: 'Transmitter moved to', fr: 'Transmetteur déplacé à' },
  'console.coverage': { en: 'Area coverage', fr: 'Couverture' },

  // ── Map ──
  'map.click_to_place': { en: 'Click on map to place transmitter', fr: 'Cliquez sur la carte pour placer le transmetteur' },
  'map.coordinates': { en: 'Coordinates', fr: 'Coordonnées' },

  // ── Models names ──
  'model.free_space': { en: 'Free Space (ITU-R P.525)', fr: 'Espace libre (UIT-R P.525)' },
  'model.egli': { en: 'Egli VHF/UHF', fr: 'Egli VHF/UHF' },
  'model.hata_urban': { en: 'Okumura-Hata (Urban)', fr: 'Okumura-Hata (Urbain)' },
  'model.hata_suburban': { en: 'Okumura-Hata (Suburban)', fr: 'Okumura-Hata (Suburbain)' },
  'model.hata_open': { en: 'Okumura-Hata (Open)', fr: 'Okumura-Hata (Ouvert)' },
  'model.cost231': { en: 'COST-231 Hata', fr: 'COST-231 Hata' },
  'model.sui': { en: 'SUI Microwave', fr: 'SUI Micro-ondes' },
  'model.ericsson9999': { en: 'Ericsson 9999', fr: 'Ericsson 9999' },
  'model.itu_p1812': { en: 'ITU-R P.1812', fr: 'UIT-R P.1812' },
  'model.itm': { en: 'Longley-Rice ITM', fr: 'Longley-Rice ITM' },
  'model.los': { en: 'Line of Sight', fr: 'Ligne de visée' },
  'model.general_purpose': { en: 'General Purpose', fr: 'Usage général' },
} as const;

export type TranslationKey = keyof typeof translations;

export function t(key: TranslationKey, locale: Locale): string {
  const entry = translations[key];
  if (!entry) return key;
  return entry[locale] || entry['en'] || key;
}

export function getLocale(): Locale {
  const stored = localStorage.getItem('rf-planner-locale');
  if (stored === 'fr' || stored === 'en') return stored;
  const browserLang = navigator.language.slice(0, 2);
  return browserLang === 'fr' ? 'fr' : 'en';
}

export function setLocale(locale: Locale) {
  localStorage.setItem('rf-planner-locale', locale);
}
