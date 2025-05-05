from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
import requests
import pycountry

app = FastAPI()
#http://127.0.0.1:8000/docs#/

#CORS middleware to allow requests from the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500"],  # The origin of JS Client (localhost)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/get_single_address_probability")
def get_single_address_probability(requested_address: str = Body(..., embed=True)):
    """
    Calculate the probability of a single address based on its neighborhood evaluation.
    Args:
        requested_address (str): The address provided by the user, passed as a request body parameter.
    Returns:
        dict: A dictionary containing the evaluation results of the neighborhood associated with the given address.
    Raises:
        ValueError: If the provided address is invalid or cannot be processed.
    """

    address_details = get_valid_address_details(requested_address)

    if (type(address_details) == str):
        return address_details
    address_data = get_address_data(address_details)
              
    return evaluate_neighborhood(address_data)

@app.post("/get_many_addresses_probability")
def get_many_addresses_probability(requested_addresses: list[str] = Body(..., embed=True)) -> list[dict]:
    """
    Processes a list of requested addresses, validates them, retrieves their details, 
    fetches associated data, and applies an algorithm to generate results.
    Args:
        requested_addresses (list[str]): A list of address strings provided in the request body.
    Returns:
        list[dict]: A list of dictionaries containing the processed results for each address.
                    Each dictionary includes the address name, its details, and associated data.
    Raises:
        Any exceptions raised by the helper functions `get_valid_address_details`, 
        `get_address_data`, or `get_algorithm_results` will propagate to the caller.
    """

    all_addresses = []
    for requested_address in requested_addresses:
        # Check if the address is valid
        address = { "name": requested_address, "details": {}, "data": {} }
        address['details'] = get_valid_address_details(requested_address)

        all_addresses.append(address)
    
    for address in all_addresses:
        address["data"] = get_address_data(address["details"])

    return get_algorithm_results(all_addresses)

def get_valid_address_details(address: str):
    """
    Retrieves and validates the details of a given address.
    Args:
        address (str): The address to be validated and processed.
    Returns:
        dict: A dictionary containing the details of the valid address.
    Raises:
        HTTPException: If the address is invalid, with a 404 status code 
        and an error message.
    """

    details, is_valid, message = get_address_details(address)
    if not is_valid:
        return message
        #raise HTTPException(status_code=404, detail=message)
    
    return details

def get_address_data(address: str) -> dict:
    #place = get_nearby_neighbourhoods(address)
    #place = get_neighbourhood_data(place)
    return get_neighbourhood_data(address)

def call_api(url, headers, params):
    """
    Call the API with the given URL and parameters.
    """

    response = requests.get(url, params=params, headers=headers)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Internal Error (API's are dead), please try again later")
    
    return response.json()

def get_address_details(address):
    """
    Check if the given address corresponds to an area no bigger than a neighborhood or city.
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        'q': address,
        'format': 'json',
        'addressdetails': 1,
        'limit': 1,
    }

    headers = {
        'User-Agent': 'address-checker-script'
    }

    data = call_api(url, headers, params)

    if not data:
        return {}, False, f"The address: {address} was not found"

    result = data[0]

    address_details = result["address"]
    address_details["lat"] = result["lat"]
    address_details["lon"] = result["lon"]
    
    accepted_place_types = set(["residential", "postcode", "city"])

    if  result["type"] in accepted_place_types:
        return address_details, True, "Address is valid"
    return {}, False, f"The address: {address} is invalid, please enter a residential address"

    #small_place_types = { "house", "residential", "street", "suburb", "neighbourhood", "city_block", "quarter", "village", "town", "city", "postcode" }

# Get Data from the API
def get_population_density_score(address_details) -> int:
    # Try Teleport API for urban area density
    density = get_urban_area_density(address_details)
    if density is not None:
        return density
    
    # Fallback to World Bank country-level density
    density = get_country_density(address_details)
    return density if density is not None else 5000  # Mock fallback

def get_urban_area_density(address_details):
    lat = address_details.get('lat')
    lon = address_details.get('lon')
    if not lat or not lon:
        return None
    
    try:
        # Get urban area slug from coordinates
        locations_url = f"https://api.teleport.org/api/locations/{lat},{lon}/"
        response = requests.get(locations_url, timeout=5)
        response.raise_for_status()
        data = response.json()
        urban_area_link = data.get('_links', {}).get('ua:item', {}).get('href')
        if not urban_area_link:
            return None
        
        # Fetch urban area details
        urban_area_slug = urban_area_link.split("/")[-2]
        details_url = f"https://api.teleport.org/api/urban_areas/{urban_area_slug}/details/"
        response = requests.get(details_url, timeout=5)
        response.raise_for_status()
        details = response.json()
        
        # Extract population and area
        population, area = None, None
        for category in details.get('categories', []):
            if category['label'] == 'Population':
                for item in category['data']:
                    if item['label'] == 'Population':
                        population = item.get('float_value')
            elif category['label'] == 'Geography':
                for item in category['data']:
                    if item['label'] == 'Area in square kilometers':
                        area = item.get('float_value')
        
        if population and area:
            return int(population / area)
    except requests.exceptions.RequestException:
        return None

def get_country_density(address_details):
    country_name = address_details.get('country', '')
    if not country_name:
        return None
    
    try:
        # Convert country name to ISO code
        country = pycountry.countries.search_fuzzy(country_name)[0]
        country_code = country.alpha_3
    except LookupError:
        return None
    
    # Fetch population and area from World Bank
    try:
        pop_url = f"http://api.worldbank.org/v2/country/{country_code}/indicator/SP.POP.TOTL?format=json&date=2021"
        area_url = f"http://api.worldbank.org/v2/country/{country_code}/indicator/AG.LND.TOTL.K2?format=json&date=2021"
        
        pop_response = requests.get(pop_url, timeout=5)
        pop_response.raise_for_status()
        pop_data = pop_response.json()
        population = pop_data[1][0]['value'] if len(pop_data) > 1 else None
        
        area_response = requests.get(area_url, timeout=5)
        area_response.raise_for_status()
        area_data = area_response.json()
        area = area_data[1][0]['value'] if len(area_data) > 1 else None
        
        if population and area:
            return int(population / area)
    except (requests.exceptions.RequestException, KeyError, IndexError):
        return None

#Crime Rate
def get_crime_score(address_details) -> int:
    """
    Fetch crime rate score (0-100) for a 1-mile radius using data.police.uk API.
    Higher score = higher crime risk.
    """
    lat = address_details.get("lat")
    lon = address_details.get("lon")

    if not lat or not lon:
        return 25  # Fallback to mock if coordinates missing

    try:
        # Get crimes within 1 mile radius for the latest month
        url = "https://data.police.uk/api/crimes-street/all-crime?date="
        params = {
            "lat": lat,
            "lng": lon,
            "date": "2025-02"
        }

        crimes = call_api(url, {}, params)
        #response = requests.get(url, params=params, timeout=10)
        #response.raise_for_status()
        #crimes = response.json()

        # Calculate crime rate score (scaled 0-100)
        total_crimes = len(crimes)
        max_crimes = 500
        return min((total_crimes / max_crimes) * 100, 100)

    except requests.exceptions.RequestException as e:
        return 25  # Fallback to mock if API fails

# Income
def get_income_score(postcode, api_key='DEMO'):
    """
    Fetches the mean household income for the given postcode and normalizes it.
    
    Parameters:
    - postcode (str): The UK postcode (e.g., 'MK9 3HG')
    - api_key (str): Your Crystal Roof API key. Use 'DEMO' for testing.
    
    Returns:
    - float: Normalized income score between 0 and 1
    """
    # Clean and encode the postcode
    postcode_clean = postcode.replace(" ", "").upper()
    url = f"https://crystalroof.co.uk/customer-api/income/mean-household-income/postcode/v1/{postcode_clean}?api_key={api_key}"

    data = call_api(url, {}, {})
    
    # Extract the mean household income
    income = data.get("mean_household_income")
    if income is None:
        raise ValueError("Income data not found in the API response.")
    
    # Normalize the income value
    income_score = normalize(income, 20000, 150000)
    
    return income_score

# Residential Ratio
def get_residential_ratio(address, radius=200):
    """
    Uses Overpass API to calculate the ratio of residential buildings in a given area.
    
    Parameters:
    - address: A textual address (e.g., "Baker Street, London")
    - radius: Radius in meters to search around the location
    
    Returns:
    - A float between 0 and 1 indicating the residential building ratio
    """
    # Get coordinates from address
    lat, lon = address.get('lat'), address.get('lon')

    # Overpass QL query to get all building types in a radius
    overpass_url = "https://overpass-api.de/api/interpreter"
    query = f"""
    [out:json][timeout:25];
    (
      way["building"](around:{radius},{lat},{lon});
    );
    out body;
    """
    headers = {
        'User-Agent': 'door-to-door-service-evaluator/1.0'
    }

    #response = requests.post(overpass_url, data=query, headers=headers)
    #response.raise_for_status()
    data = call_api(overpass_url, headers, { 'data': query })

    building_tags = [el.get('tags', {}).get('building', '').lower() for el in data.get('elements', [])]

    if not building_tags:
        return 0.0  # No buildings found

    residential_count = sum(1 for b in building_tags if 'residential' in b or b in ['house', 'apartments', 'detached', 'semidetached_house'])
    total_count = len(building_tags)

    return residential_count / total_count if total_count > 0 else 0.0


def get_neighbourhood_data(address_details) -> dict:
    mock_data = {
        'population_density': get_population_density_score(address_details),
        'crime_rate': get_crime_score(address_details), #25,
        'income': 60000, # get_income_score(address_details["postcode"])
        'residential_ratio': get_residential_ratio(address_details),# 0.8,
        'noise_level': 30,
        'healthcare_access': 85,
        'community_engagement': 70,
        'environmental_quality': 75,
    }
    
    return mock_data

CRITERIA_WEIGHTS = {
    'population_density': 0.2,
    'crime_rate': 0.2,
    'income': 0.15,
    'residential_ratio': 0.08,
    'noise_level': 0.05,
    'healthcare_access': 0.3,
    'community_engagement': 0.1,
    'environmental_quality': 0.12,
}

def normalize(value, min_val, max_val, invert=False):
    norm = (value - min_val) / (max_val - min_val)
    return 1 - norm if invert else norm

def calculate_rating(score):
    if score >= 1.5:
        return "Excellent"
    elif score >= 0.8:
        return "Good"
    elif score >= 0.4:
        return "Average"
    elif score >= 0.2:
        return "Poor"
    else:
        return "Very Poor"

def evaluate_neighborhood(data: dict[str, float]) -> float:
    # Normalize each criterion (mock min/max range)
    normalized_scores = {
        'population_density': normalize(data['population_density'], 100, 10000),
        'crime_rate': normalize(data['crime_rate'], 0, 500, invert=True),
        'income': normalize(data['income'], 20000, 150000),
        'residential_ratio': normalize(data['residential_ratio'], 0, 1),
        'noise_level': normalize(data['noise_level'], 0, 100, invert=True),
        'healthcare_access': normalize(data['healthcare_access'], 0, 100),
        'community_engagement': normalize(data['community_engagement'], 0, 100),
        'environmental_quality': normalize(data['environmental_quality'], 0, 100),
    }

    # Weighted sum
    total_score = sum(
        CRITERIA_WEIGHTS[k] * normalized_scores[k] for k in CRITERIA_WEIGHTS
    )

    rating = calculate_rating(total_score)
    
    return { "rating": rating, "score": total_score }

def get_algorithm_results(addresses: list) -> dict:
    results = []
    for address in addresses:
        result = { "address": address["name"], "data": evaluate_neighborhood(address['data']) }
        results.append(result)

    return results