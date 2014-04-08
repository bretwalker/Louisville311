import csv
import re
import sys, getopt
import time
import logging
from datetime import datetime, timedelta
import requests
    
class ThreeOneOneScraper():
    def __init__(self, contact_email, start_num, sleep):
        self.sleep = sleep
        
        self.start_num = start_num
        
        self.input_re = re.compile(r'<input.*?name="(?P<name>\S+?)" (?:\S+="\S+?")? (?:value="(?P<value>\S+?)")?.*?>')
        self.case_event_re = re.compile(r"""__doPostBack\('(?P<case_event>ctl\d+?\$DPContentPlaceHolder\d+?\$LookupTC\$SearchResultTab\$LookupResultsGrid\$ctl\d+?\$mainViewLink)',''\)">\d+?</a>""")
        self.detail_re = re.compile(r'lbl_ServiceNumber">(?P<service_number>\d+?)</span>.*lblSRDate">(?P<date>.*?)</span>.*lbl_ProblemDesc">(?P<problem>.*?)</span>.*lbl_Address">(?P<address>.*?) (?:LOUISVILLE, KY|KY).*?</span>.*(?:lbl_Location">(?P<location>.*?)</span>.*)?lbl_AssignFlag">(?P<inspector_assigned>.*?)</span>.*lbl_InspFlag">(?P<inspected>.*?)</span>.*lbl_InworkFlag">(?P<work_required>.*?)</span>.*lbl_ResFlag">(?P<request_completed>.*?)</span>.*lbl_Resolution">(?P<resolution_date>.*?)</span>.*lblResolutionCode">(?P<resolution>.*?)</span>', flags=re.DOTALL|re.IGNORECASE)
        self.no_results_re = re.compile(r'<div id="ctl00_DPContentPlaceHolder1_LookupTC_SearchResultTab"(?: style="display:none;visibility:hidden;")?>\s+<span id="ctl00_DPContentPlaceHolder1_LookupTC_SearchResultTab_lblSearchResult" class="outputText"></span>\s+<div>\s+</div>\s+</div>')
        self.apt_suite_re = re.compile(r'Unit/Suite (\d+|[a-z])', flags=re.IGNORECASE)
        
        self.base_url = 'https://dp.louisvillemsd.org/dpcrm8/CustomerService/ServiceRequestLookup.aspx'
        self.headers = {}
        self.headers['Referer'] = 'https://dp.louisvillemsd.org/dpcrm8/CustomerService/ServiceRequestLookup.aspx'
        self.headers['Origin'] = 'https://dp.louisvillemsd.org/'
        self.headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/34.0.1847.92 Safari/537.36'
        self.headers['X-Contact-Person'] = contact_email
    
    def get_from_match(self, match, key):
        try:
            return match.group(key)
        except IndexError:
            None
        
    def get_post_data_from_html(self, html):
        """
        Adds the form values needed in order to get a response from the ASP.NET app.
        """
        post_data = {}
        for input_match in self.input_re.finditer(html):
            post_data[input_match.group('name')] = '' if input_match.group('value') == None else input_match.group('value')
            
        post_data['__ASYNCPOST'] = 'false'
        post_data['__EVENTARGUMENT'] = '' 
        post_data['ctl00$DPContentPlaceHolder1$LookupTC$AddressTab$AddressControl1$DateFrom'] = ''
        post_data['ctl00$DPContentPlaceHolder1$LookupTC$AddressTab$AddressControl1$DateTo'] = ''
        post_data['ctl00$DPContentPlaceHolder1$LookupTC$AddressTab$AddressControl1$text_StName'] = ''
        post_data['ctl00$DPContentPlaceHolder1$LookupTC$AddressTab$AddressControl1$ddl_StSuffix'] = '--'
        post_data['ctl00$DPContentPlaceHolder1$LookupTC$AddressTab$AddressControl1$ddl_StDirection'] = '--'
        if 'ctl00_DPContentPlaceHolder1_LookupTC_ClientState' in post_data:
            post_data['ctl00_DPContentPlaceHolder1_LookupTC_ClientState'] = post_data['ctl00_DPContentPlaceHolder1_LookupTC_ClientState'].replace('&quot;', '"')
        post_data['ctl00$ScriptManager1'] = 'ctl00$DPContentPlaceHolder1$UpdatePanel1|ctl00$DPContentPlaceHolder1$LookupTC$AddressTab$AddressControl1$addressSearch'
        post_data['ctl00$DPContentPlaceHolder1$LookupTC$AddressTab$AddressControl1$ddl_State'] = 'KY'
        post_data['__AjaxControlToolkitCalendarCssLoaded'] = ''
        return post_data
    
    def parse_service_request(self, case_event, cookies, post_data):
        post_data['__EVENTTARGET'] = 'ctl00$DPContentPlaceHolder1$LookupTC$APNOTab$ApNumberControl1$apNumberSearch'
        post_data['ctl00$DPContentPlaceHolder1$LookupTC$APNOTab$ApNumberControl1$text_APNumber'] = case_event
        
        time.sleep(self.sleep)
        list_response = requests.post(self.base_url, data=post_data, cookies=cookies, headers=self.headers)
        if self.no_results_re.search(list_response.text) or 'service request not found' in list_response.text.lower():
            logging.info('No results for request {0}'.format(case_event))
            return False
            
        for case_event_match in self.case_event_re.finditer(list_response.text):
            post_data['__EVENTTARGET'] = case_event_match.group('case_event')
            
            time.sleep(self.sleep)
            detail_response = requests.post(self.base_url, data=post_data, cookies=cookies, headers=self.headers)
            matches = self.detail_re.search(detail_response.text)
            try:
                logging.info('About to process service number: ' + matches.group('service_number'))
            except:
                logging.warn('Regex did not match (can happen with suggestions with no address)')
                return False
    
            resolution_date = self.get_from_match(matches, 'resolution_date')
            resolution_description = self.get_from_match(matches, 'resolution_description')
            location_detail = self.get_from_match(matches, 'location_detail')
        
            service_attributes = {
                'problem': matches.group('problem'),
                'date': datetime.strptime(matches.group('date'), "%A, %B %d, %Y").date(),
                'address': matches.group('address'),
                'inspected': 'yes' in matches.group('inspected').lower(),
                'inspector_assigned': 'yes' in matches.group('inspector_assigned').lower(),
                'request_completed': 'yes' in  matches.group('request_completed').lower(),
                'resolution_date': None if resolution_date is None or resolution_date == 'NA' else datetime.strptime(resolution_date, "%A, %B %d, %Y").date(),
                'resolution_description': resolution_description,
                'service_number': matches.group('service_number'),
                'work_required': 'yes' in matches.group('work_required').lower(),
                'location_detail': location_detail
            }
        
            return service_attributes
                                
    def update(self):
        consecutive_failures = 0
        
        csv_fieldnames = ['problem', 'date', 'address', 'inspected', 'inspector_assigned', 'request_completed', 'resolution_date', 'resolution_description', 'service_number', 'work_required', 'location_detail' ]
        
        with open('out.csv', 'wb') as csvfile:
            writer = csv.DictWriter(csvfile, csv_fieldnames, delimiter=',')
                                        
            while True:
                main_page_response = requests.get(self.base_url)
                post_data = self.get_post_data_from_html(main_page_response.text)
            
                request_results = self.parse_service_request(self.start_num, main_page_response.cookies, post_data)
                self.start_num += 1
                
                if not request_results:
                    consecutive_failures += 1
                else:
                    consecutive_failures = 0
                    writer.writerow(request_results)
                
                if consecutive_failures == 5:
                    logging.info('Got 5 consecutive failures. Must be at the end.')
                    return
                
def main(argv):
    logging.basicConfig(filename='/tmp/311.log', level=logging.INFO)
    start_num = 0
    sleep = 2
    email = None
    
    try:
       opts, args = getopt.getopt(argv,"hn:e:s:",["startnum=","sleep=","email="])
    except getopt.GetoptError:
       print '311.py -n <start_number> -s <sleep_time> -e <contact email>'
       sys.exit(2)
    for opt, arg in opts:
       if opt == '-h':
          print '311.py -n <start_number> -s <sleep_time> -e <contact email>'
          sys.exit()
       elif opt in ("-n", "--startnum"):
          start_num = arg
       elif opt in ("-s", "--sleep"):
          sleep = arg
       elif opt in ("-e", "--email"):
           email = arg

    if not email:
        print 'Must supply email with -e argument. Give Metro someone to contact in case of a problem.'
        sys.exit(2)
    
    updater = ThreeOneOneScraper(email, int(start_num), sleep)
    updater.update()

if __name__ == "__main__":
    main(sys.argv[1:])
