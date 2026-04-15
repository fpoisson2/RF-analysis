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
  'rx.position': { en: 'Position', fr: 'Position' },
  'rx.place': { en: 'Place RX (click on map)', fr: 'Placer le récepteur (cliquer sur la carte)' },
  'rx.move': { en: 'Move RX', fr: 'Déplacer le récepteur' },
  'rx.placing': { en: 'Placing…', fr: 'Placement…' },
  'rx.remove': { en: 'Remove RX', fr: 'Retirer le récepteur' },
  'tx.place': { en: 'Place TX (click on map)', fr: 'Placer l\'émetteur (cliquer sur la carte)' },
  'tx.placing': { en: 'Placing…', fr: 'Placement…' },

  // ── Help tooltips ──
  'help.tx.height': {
    en: 'Antenna height above ground level (AGL), in meters. Higher = better coverage and reduces obstruction by terrain/buildings/trees.',
    fr: 'Hauteur de l\'antenne au-dessus du sol (AGL), en mètres. Plus haut = meilleure couverture et moins d\'obstruction par le terrain, les bâtiments et les arbres.',
  },
  'help.sig.frequency': {
    en: 'Carrier frequency (MHz). Lower frequencies (VHF/UHF) propagate further and penetrate obstacles better. Higher frequencies (microwave) need clear line-of-sight.',
    fr: 'Fréquence porteuse (MHz). Les basses fréquences (VHF/UHF) portent plus loin et pénètrent mieux les obstacles. Les hautes fréquences (micro-ondes) demandent une visibilité directe.',
  },
  'help.sig.power': {
    en: 'Transmitter output power into the feeder, in Watts. The actual radiated power (ERP/EIRP) accounts for antenna gain and feeder loss.',
    fr: 'Puissance de sortie de l\'émetteur dans le câble, en Watts. La puissance réellement rayonnée (PAR/PIRE) tient compte du gain d\'antenne et des pertes de câble.',
  },
  'help.sig.bandwidth': {
    en: 'Channel bandwidth in MHz. Affects noise floor and the SNR computation; does not change the propagation path loss.',
    fr: 'Largeur de bande du canal en MHz. Influence le plancher de bruit et le calcul du SNR ; ne change pas l\'affaiblissement de propagation.',
  },
  'help.feed.loss': {
    en: 'Total cable + connector loss between transmitter and antenna, in dB. Typical: 1-3 dB short coax, up to 10 dB long runs.',
    fr: 'Perte totale câble + connecteurs entre l\'émetteur et l\'antenne, en dB. Typique : 1-3 dB pour du coax court, jusqu\'à 10 dB pour de longs trajets.',
  },
  'help.ant.gain': {
    en: 'Antenna gain in dBi (relative to isotropic). 2.15 dBi = dipole, 5-12 dBi = directional Yagi/panel, 20+ dBi = parabolic dish.',
    fr: 'Gain d\'antenne en dBi (par rapport à l\'isotrope). 2.15 dBi = dipôle, 5-12 dBi = Yagi/panneau directionnel, 20+ dBi = parabole.',
  },
  'help.ant.azimuth': {
    en: 'Direction the antenna is pointed, in degrees clockwise from north. Used only for directional antennas.',
    fr: 'Direction de pointage de l\'antenne, en degrés horaires depuis le nord. Utile uniquement pour antennes directionnelles.',
  },
  'help.ant.tilt': {
    en: 'Antenna mechanical down-tilt (positive) or up-tilt (negative), in degrees.',
    fr: 'Inclinaison mécanique de l\'antenne vers le bas (positif) ou vers le haut (négatif), en degrés.',
  },
  'help.ant.hbw': {
    en: 'Horizontal half-power beamwidth in degrees. 360° for omnidirectional, 60-90° for sectorial, narrower for directional.',
    fr: 'Largeur de faisceau horizontal à -3 dB, en degrés. 360° pour omnidirectionnelle, 60-90° pour sectorielle, plus étroit pour directive.',
  },
  'help.ant.vbw': {
    en: 'Vertical half-power beamwidth in degrees.',
    fr: 'Largeur de faisceau vertical à -3 dB, en degrés.',
  },
  'help.ant.pattern': {
    en: 'Antenna radiation pattern model used for the gain calculation in each direction.',
    fr: 'Modèle de diagramme de rayonnement utilisé pour calculer le gain dans chaque direction.',
  },
  'help.rx.height': {
    en: 'Receiver antenna height above ground level, in meters. Lifting RX above obstacles (trees, buildings) clears the Fresnel zone and improves signal.',
    fr: 'Hauteur de l\'antenne réceptrice au-dessus du sol, en mètres. Élever le RX au-dessus des obstacles (arbres, bâtiments) dégage la zone de Fresnel et améliore le signal.',
  },
  'help.rx.gain': {
    en: 'Receiver antenna gain in dBi. Adds to the received signal level.',
    fr: 'Gain de l\'antenne réceptrice en dBi. S\'ajoute au niveau de signal reçu.',
  },
  'help.rx.sensitivity': {
    en: 'Minimum signal level (dBm) the receiver can demodulate. Coverage is judged by comparing received signal to this threshold.',
    fr: 'Niveau de signal minimum (dBm) que le récepteur peut démoduler. La couverture est évaluée en comparant le signal reçu à ce seuil.',
  },
  'help.mdl.model': {
    en: 'Propagation model. ITM (Longley-Rice) is recommended for general terrain. Free-space ignores obstructions. Hata/COST231 for urban cellular.',
    fr: 'Modèle de propagation. ITM (Longley-Rice) recommandé en terrain général. Espace libre ignore les obstructions. Hata/COST231 pour cellulaire urbain.',
  },
  'help.mdl.reliability': {
    en: 'Time/location reliability percentage. 50% = median path loss; higher values add a safety margin (worst-case design).',
    fr: 'Pourcentage de fiabilité temps/localisation. 50% = perte médiane ; valeurs plus hautes = marge de sécurité (dimensionnement pessimiste).',
  },
  'help.mdl.diffraction': {
    en: 'Knife-edge diffraction model used to compute additional loss caused by terrain/buildings/trees blocking the Fresnel zone.',
    fr: 'Modèle de diffraction utilisé pour calculer la perte supplémentaire causée par le terrain, bâtiments et arbres bloquant la zone de Fresnel.',
  },
  'help.env.noise': {
    en: 'Background noise floor at the receiver, in dBm. Determines the SNR (signal − noise floor).',
    fr: 'Plancher de bruit au récepteur, en dBm. Détermine le rapport S/B (signal − plancher de bruit).',
  },
  'help.env.elevation': {
    en: 'Terrain model: DTM = bare earth, DSM = surface (with buildings/canopy). LiDAR data is used when available, otherwise SRTM (~30m).',
    fr: 'Modèle de terrain : MNT = sol nu, MNS = surface (avec bâtiments/canopée). Les données LiDAR sont utilisées si disponibles, sinon SRTM (~30m).',
  },
  'help.out.resolution': {
    en: 'Pixel size of the coverage raster, in meters. Smaller = sharper but slower (~quadratic in compute).',
    fr: 'Taille des pixels de la carte de couverture, en mètres. Plus petit = plus net mais plus lent (~quadratique en calcul).',
  },
  'help.out.radius': {
    en: 'Coverage area radius around the transmitter, in km. Larger = more area covered but more compute.',
    fr: 'Rayon de la zone de couverture autour de l\'émetteur, en km. Plus grand = plus de surface mais plus de calcul.',
  },
  'help.out.units': {
    en: 'What the colour map represents: dBm = received signal power, dB = SNR (signal vs noise), dBuV/m = electric field strength.',
    fr: 'Ce que représente la carte couleur : dBm = puissance reçue, dB = SNR (signal vs bruit), dBuV/m = intensité du champ électrique.',
  },

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
  'model.itu_p1812': { en: 'ITU-R P.1812 (simplified)', fr: 'UIT-R P.1812 (simplifié)' },
  'model.itm': { en: 'Longley-Rice ITM (simplified)', fr: 'Longley-Rice ITM (simplifié)' },
  'model.itm_ntia': { en: 'Longley-Rice ITM (NTIA reference)', fr: 'Longley-Rice ITM (référence NTIA)' },
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
