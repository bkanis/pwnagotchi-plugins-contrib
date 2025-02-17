import logging
import io
import subprocess
import os
import json
import pwnagotchi.plugins as plugins
from threading import Lock
from pwnagotchi.ui.components import LabeledValue
from pwnagotchi.ui.view import BLACK
import pwnagotchi.ui.fonts as fonts


class hashie(plugins.Plugin):
    __author__ = 'junohea.mail@gmail.com'
    __version__ = '1.0.3'
    __license__ = 'GPL3'
    __description__ = '''
                        Attempt to automatically convert pcaps to a crackable format.
                        If successful, the files  containing the hashes will be saved 
                        in the same folder as the handshakes. 
                        The files are saved in their respective Hashcat format:
                          - EAPOL + PMKID hashes are saved as *.22000
                        All PCAP files without enough information to create a hash are
                          stored in a file that can be read by the webgpsmap plugin.
                        
                        Why use it?:
                          - Automatically convert handshakes to crackable formats! 
                              We dont all upload our hashes online ;)
                          - Repair PMKID handshakes that hcxpcaptool misses
                          - If running at time of handshake capture, on_handshake can
                              be used to improve the chance of the repair succeeding
                          - Be a completionist! Not enough packets captured to crack a network?
                              This generates an output file for the webgpsmap plugin, use the
                              location data to revisit networks you need more packets for!
                          
                        Additional information:
                          - Currently requires hcxpcaptool compiled and installed
                          - Attempts to repair PMKID hashes when hcxpcaptool cant find the SSID
                            - hcxpcaptool sometimes has trouble extracting the SSID, so we 
                                use the raw 16800 output and attempt to retrieve the SSID via tcpdump
                            - When access_point data is available (on_handshake), we leverage 
                                the reported AP name and MAC to complete the hash
                            - The repair is very basic and could certainly be improved!
                        Todo:
                          Improve the code, a lot
                        '''
    
    def __init__(self):
        logging.info("[hashie] plugin loaded")
        self.lock = Lock()

    # called when everything is ready and the main loop is about to start
    def on_config_changed(self, config):
        handshake_dir = config['bettercap']['handshakes']
        
        if 'interval' not in self.options or not (self.status.newer_then_hours(self.options['interval'])):
            logging.info('[hashie] Starting batch conversion of pcap files')
            with self.lock:
                self._process_stale_pcaps(handshake_dir)

    def on_handshake(self, agent, filename, access_point, client_station):
        with self.lock:
            handshake_status = []
            fullpathNoExt = filename.split('.')[0]
            name = filename.split('/')[-1:][0].split('.')[0]
            
            if os.path.isfile(fullpathNoExt +  '.22000'):
                handshake_status.append('Already have {}.22000 (EAPOL + PMKID)'.format(name))
            elif self._writeEAPOL(filename):
                handshake_status.append('Created {}.22000 (EAPOL + PMKID) from pcap'.format(name))

            if handshake_status:
                logging.info('[hashie] Good news:\n\t' + '\n\t'.join(handshake_status))
    
    def _writeEAPOL(self, fullpath):
        fullpathNoExt = fullpath.split('.')[0]
        filename = fullpath.split('/')[-1:][0].split('.')[0]
        result = subprocess.getoutput('hcxpcaptool -o {}.22000 {} >/dev/null 2>&1'.format(fullpathNoExt,fullpath))
        if os.path.isfile(fullpathNoExt +  '.22000'):
            logging.debug('[hashie] [+] EAPOL Success: {}.22000 created'.format(filename))
            return True
        else:
            return False
           
    def _process_stale_pcaps(self, handshake_dir):
        handshakes_list = [os.path.join(handshake_dir, filename) for filename in os.listdir(handshake_dir) if filename.endswith('.pcap')]
        failed_jobs = []
        successful_jobs = []
        lonely_pcaps = []
        for num, handshake in enumerate(handshakes_list):
            fullpathNoExt = handshake.split('.')[0]
            pcapFileName = handshake.split('/')[-1:][0]
            if not os.path.isfile(fullpathNoExt + '.22000'): #if no 22000, try
                if self._writeEAPOL(handshake):
                    successful_jobs.append('22000: ' + pcapFileName)
                else:
                    failed_jobs.append('22000: ' + pcapFileName)
                    lonely_pcaps.append(handshake)
                    logging.debug('[hashie] Batch job: added {} to lonely list'.format(pcapFileName))

            if ((num + 1) % 50 == 0) or (num + 1 == len(handshakes_list)): #report progress every 50, or when done
                logging.info('[hashie] Batch job: {}/{} done ({} fails)'.format(num + 1,len(handshakes_list),len(lonely_pcaps)))
        if successful_jobs:
            logging.info('[hashie] Batch job: {} new handshake files created'.format(len(successful_jobs)))
        if lonely_pcaps:
            logging.info('[hashie] Batch job: {} networks without enough packets to create a hash'.format(len(lonely_pcaps)))
            self._getLocations(lonely_pcaps)
    
    def _getLocations(self, lonely_pcaps):
        #export a file for webgpsmap to load
        with open('/root/.incompletePcaps','w') as isIncomplete:
            count = 0
            for pcapFile in lonely_pcaps:
                filename = pcapFile.split('/')[-1:][0] #keep extension
                fullpathNoExt = pcapFile.split('.')[0]
                isIncomplete.write(filename + '\n')
                if os.path.isfile(fullpathNoExt +  '.gps.json') or os.path.isfile(fullpathNoExt +  '.geo.json') or os.path.isfile(fullpathNoExt +  '.paw-gps.json'):
                    count +=1
            if count != 0:
                logging.info('[hashie] Used {} GPS/GEO/PAW-GPS files to find lonely networks, go check webgpsmap! ;)'.format(str(count)))
            else:
                logging.info('[hashie] Could not find any GPS/GEO/PAW-GPS files for the lonely networks'.format(str(count)))
        
    def _getLocationsCSV(self, lonely_pcaps):
        #in case we need this later, export locations manually to CSV file, needs try/catch/paw-gps format/etc.
        locations = []
        for pcapFile in lonely_pcaps:
            filename = pcapFile.split('/')[-1:][0].split('.')[0]
            fullpathNoExt = pcapFile.split('.')[0]
            if os.path.isfile(fullpathNoExt +  '.gps.json'):
                with open(fullpathNoExt + '.gps.json','r') as tempFileA:
                    data = json.load(tempFileA)
                    locations.append(filename + ',' + str(data['Latitude']) + ',' + str(data['Longitude']) + ',50')
            elif os.path.isfile(fullpathNoExt +  '.geo.json'):
                with open(fullpathNoExt + '.geo.json','r') as tempFileB:
                    data = json.load(tempFileB)
                    locations.append(filename + ',' + str(data['location']['lat']) + ',' + str(data['location']['lng']) + ',' + str(data['accuracy']))
            elif os.path.isfile(fullpathNoExt +  '.paw-gps.json'):
                with open(fullpathNoExt + '.paw-gps.json','r') as tempFileC:
                    data = json.load(tempFileC)
                    locations.append(filename + ',' + str(data['lat']) + ',' + str(data['long']) + ',50')
        if locations:
            with open('/root/locations.csv','w') as tempFileD:
                for loc in locations:
                    tempFileD.write(loc + '\n')
            logging.info('[hashie] Used {} GPS/GEO files to find lonely networks, load /root/locations.csv into a mapping app and go say hi!'.format(len(locations)))