import argparse
import datetime
import json
import matplotlib.pyplot as plt
import os
import pandas as pd
import urllib.request
import geopandas
import pycountry
import geoplot as gplt
from datetime import date

from manubot.cite.citekey import url_to_citekey
from manubot.cite.doi import get_short_doi_url

def convert_date(git_date):
    '''Reformat git commit style datetimes (ISO 8601) to Month DD, YYYY.
    Throws a ValueError if git_date cannot be parsed as an ISO 8601 datetime.
    '''
    # 'Z' indicates Coordinated Universal Time (UTC)
    # Replace with '+00:00', which is the UTC representation recognized
    # by the parser
    # https://en.wikipedia.org/wiki/ISO_8601#Coordinated_Universal_Time_(UTC)
    git_date = git_date.replace('Z', '+00:00')
    
    # Remove the leading zero of the day
    # Assumes the year will not begin with 0
    return datetime.datetime.fromisoformat(git_date).strftime('%B %d, %Y').replace(' 0', ' ')

def extract_citekey(results_url):
    '''Extract a Manubot citation key from the results URL. Uses short DOI if
    citekey is a DOI and contains parentheses.'''
    citekey = url_to_citekey(results_url)
    # citekey typically in the form doi:10.1101/2020.05.31.20114520 or
    # url:https://clinicaltrials.gov/ct2/show/results/NCT04323592
    if(citekey.startswith ('doi:') and ('(' in citekey or ')' in citekey)):
        short_doi_url = get_short_doi_url(citekey)
        # URL in the form https://doi.org/ggvw2s
        citekey = short_doi_url.replace('https://doi.org', 'doi:10')
    return citekey

def assign_ISO(countries):
    # Match country names with ISO codes
    # Input: pd.Series of country names
    # Returns: dictionary of matches

    # Need to hard code a few countries that aren't registered using standard names, so
    # initializing the single_country_codes database with these values
    country_codes = {"South Korea": "KOR", "Democratic Republic of Congo": "COD",
                     "Democratic Republic of the Congo": "COD"}

    # Identify the most likely 3-letter ISO code for each country
    failed_matches = list()
    for country in countries:
        if country not in country_codes.keys():
            try:
                hit = pycountry.countries.get(name=country)
                if hit == None:
                    # If the name isn't an exact match, try alternatives
                    # .search_fuzzy matching returns a list, whereas .get retrieves data as class Country
                    hit = pycountry.countries.search_fuzzy(country)
                    if len(hit) > 1:
                        hit = pycountry.countries.search_fuzzy(country + ",")
                    elif type(hit) == None:
                        hit = pycountry.countries.get(official_name=country)
            except LookupError:
                failed_matches.append(country)
                continue

            if type(hit) == list and len(hit) == 1:
                country_codes[country] = hit[0].alpha_3
            elif type(hit) == list or type(hit) == None:
                failed_matches.append(country)
            else:
                country_codes[country] = hit.alpha_3

    # Print warning about failures and return successes as dictionary
    print("Failed to assign country codes to:", ", ".join(failed_matches))
    return(country_codes)

# Inspired by https://github.com/greenelab/meta-review/blob/master/analyses/deep-review-contrib/03.contrib-stats.ipynb
def main(args):
    '''Extract statistics from the EBM Data Lab COVID-19 TrialsTracker dataset'''
    ebm_stats = dict()
    now = datetime.datetime.utcnow()
    ebm_stats['ebm_update_time_utc'] = now.isoformat()

    if('EBM_COMMIT_SHA' in os.environ):
        ebm_stats['ebm_commit_sha'] = os.environ['EBM_COMMIT_SHA']
    if('EBM_COMMIT_DATE' in os.environ):
        ebm_stats['ebm_commit_date'] = os.environ['EBM_COMMIT_DATE']
        ebm_stats['ebm_commit_date_pretty'] = convert_date(os.environ['EBM_COMMIT_DATE'])

    trials_df = pd.read_json(args.input_json, orient='split')
    # Use header from the HTML table
    # https://github.com/ebmdatalab/covid_trials_tracker-covid/blob/6c2b9965b170aa6c53e7f755692a4f221de694bf/docs/results/index.html#L56
    # Those are the same order but different names from the original dataframe
    # https://github.com/ebmdatalab/covid_trials_tracker-covid/blob/6c2b9965b170aa6c53e7f755692a4f221de694bf/notebooks/diffable_python/ictrp_data_handling.py#L544
    header = ['index', 'trial_id', 'registry', 'registration_date', 'start_date', \
              'retrospective_registration', 'sponsor', 'recruitment_status', \
              'phase', 'study_type', 'countries', 'title', 'study_category', \
              'intervention', 'intervention_list', 'enrollment', \
              'primary_completion_date', 'full_completion_date', 'registy_url', \
              'results_type', 'results_published_date', 'results_url', 'last_updated', \
              'cross_registration']
    assert (len(header) == len(trials_df.columns))
    trials_df.columns = header
    trials_df = trials_df.set_index('index')
    
    ebm_stats['ebm_trials'] = f'{len(trials_df.index):,}'
    
    # Get the most recent trial update
    most_recent_update = pd.to_datetime(trials_df['last_updated']).max()
    # Remove the leading zero of the day
    # Assumes the year will not begin with 0
    most_recent_update = most_recent_update.strftime('%B %d, %Y').replace(' 0', ' ')
    ebm_stats['ebm_date_pretty'] = most_recent_update
    
    trial_results = trials_df[trials_df['results_url'] != 'No Results']['results_url']
    ebm_stats['ebm_trials_results'] = f'{len(trial_results):,}'
    
    # Some results entries have multiple URLs
    trial_results_citekeys = [extract_citekey(results_url) for results in trial_results for results_url in results.split()]
    ebm_stats['ebm_trials_results_citekeys'] = sorted(set(trial_results_citekeys))
    
    plt.rc('font', size=14)
    plt.rc('figure', titlesize=24)
    fig, axes = plt.subplots(nrows=2, ncols=2, figsize=(20, 12), constrained_layout=True)
    
    # Plot trial recruitment status
    # Only include trials with a recruitment status
    recruitment_counts = trials_df['recruitment_status'].value_counts(ascending=True)
    recruitment_counts = recruitment_counts.drop(labels='No Status Given')
    ax = recruitment_counts.plot(kind='barh', ax=axes[0, 0])
    ax.set_title('Clinical trials recruitment status')

    # Plot trial phase
    # Only include trials with a reported phase
    phase_counts = trials_df['phase'].value_counts(ascending=True)
    phase_counts = phase_counts.drop(labels='Not Applicable')
    ax = phase_counts.plot(kind='barh', ax=axes[0, 1])
    ax.set_title('Clinical trials phase')
    
    # Plot study type
    # Only include study types used in >= 5 trials
    study_type_counts = trials_df['study_type'].value_counts(ascending=True)
    study_type_counts = study_type_counts[study_type_counts >= 5]
    ax = study_type_counts.plot(kind='barh', ax=axes[1, 0])
    ax.set_title('Clinical trials study type')
    
    # Plot common interventions
    # Only include trials with an intervention and interventions in >= 10 trials
    intervention_counts = trials_df['intervention'].value_counts(ascending=True)
    intervention_counts = intervention_counts.drop(labels='No Intervention')
    intervention_counts = intervention_counts[intervention_counts >= 10]
    ax = intervention_counts.plot(kind='barh', ax=axes[1, 1])
    ax.set_title('Clinical trials common interventions')
    
    fig.savefig(args.output_figure + '.png', bbox_inches = "tight")
    fig.savefig(args.output_figure + '.svg', bbox_inches = "tight")

    print(f'Wrote {args.output_figure}.png and {args.output_figure}.svg')
    
    # Identify the names of each country in single-country and multi-country clinical trials
    # Multi refers to trials that have multiple country names, comma-separated
    # One trial lists every country on Earth and formatted the data inconsistently, so drop it
    valid_country = trials_df[trials_df['countries'] != "No Country Given"]
    valid_country = valid_country[valid_country['trial_id'] != "ISRCTN80453162"]
    single_countries = valid_country['countries'][~valid_country['countries'].str.contains(',')]
    multi_countries = valid_country["countries"][valid_country["countries"].str.contains(',')]
    multi_countries = pd.Series(
        [country for country_list in multi_countries.str.split(',') for country in country_list]
    )

    # Identify the 3-letter ISO codes for each unique country
    unique_countries = single_countries.append(multi_countries).str.strip().drop_duplicates()
    country_codes = pd.DataFrame.from_dict(assign_ISO(unique_countries), orient="index", columns=["iso_a3"])

    # Map the ISO codes onto the country data and count the frequency
    single_countries_codes = pd.DataFrame(single_countries, index=single_countries).join(country_codes)["iso_a3"]
    single_countries_codes = single_countries_codes.dropna()
    single_countries_counts = single_countries_codes.value_counts().rename("single_country_counts")

    multi_countries_codes = pd.DataFrame(multi_countries.str.strip(), index=multi_countries.str.strip()).join(country_codes)["iso_a3"]
    multi_countries_codes = multi_countries_codes.dropna()
    multi_countries_counts = multi_countries_codes.value_counts().rename("multi_country_counts")

    # Map frequency data onto the geopandas geographical data
    world_data = geopandas.read_file(geopandas.datasets.get_path('naturalearth_lowres')).set_index("iso_a3")
    countries_mapping = world_data.merge(
        pd.DataFrame(single_countries_counts), how="inner", left_index=True, right_index=True).merge(
        pd.DataFrame(multi_countries_counts), how="inner", left_index=True, right_index=True)

    # Generate two-part choropleth visualizing world map with number of clinical trial data counted
    fig, (ax1, ax2) = plt.subplots(nrows=2, ncols=1, figsize=(20, 16))
    ax1.set_title("Locations of Single-Country Clinical Trials")
    ax1 = gplt.choropleth(countries_mapping, hue = countries_mapping['single_country_counts'],
                        legend=True, ax=ax1) #countries_mapping.plot(column='single_country_counts', ax=ax1, legend=True)
    ax2.set_title("Locations of Multi-Country Clinical Trials")
    ax2 = gplt.choropleth(countries_mapping, hue = countries_mapping['multi_country_counts'],
                          legend=True, ax=ax2)
    ax2.annotate(f'Source: EBM Data Lab COVID-19 TrialsTracker, %s' % date.today().strftime("%b-%d-%Y"),
                 xy=(-168, -68))

    plt.savefig(args.output_map + '.png', bbox_inches = "tight")
    plt.savefig(args.output_map + '.svg', bbox_inches = "tight")

    print(f'Wrote {args.output_map}.png and {args.output_map}.svg')
    exit(0)
    
    # The placeholder will be replaced by the actual SHA-1 hash in separate
    # script after the updated image is committed
    ebm_stats['ebm_trials_figure'] = \
        f'https://github.com/greenelab/covid19-review/raw/$FIGURE_COMMIT_SHA/{args.output_figure}.svg'
    
    # Tabulate number of trials for pharmaceuticals of interest
    ebm_stats['ebm_tocilizumab_ct'] = str(trials_df['intervention'].str.contains('tocilizumab', case=False).sum())
    
    with open(args.output_json, 'w') as out_file:
        json.dump(ebm_stats, out_file, indent=2, sort_keys=True)
    print(f'Wrote {args.output_json}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('input_json',
                        help='Path of the EBM Data Lab COVID-19 TrialsTracker ' \
                        'input JSON file',
                        type=str)
    parser.add_argument('output_json',
                        help='Path of the JSON file with extracted statistics',
                        type=str)
    parser.add_argument('output_figure',
                        help='Path of the output figure with clinical trials ' \
                        'statistics without file type extension. Will be saved ' \
                        'as .png and .svg.',
                        type=str)
    parser.add_argument('output_map',
                         help='Path of the output choropleth (world map figure) ' \
                        'with geographic clinical trial frequencies, without file ' \
                        'type extension. Will be saved as .png and .svg.',
                        type=str)

    args = parser.parse_args()
    main(args)
