import gc
import os

import pandas as pd
import pickle
import geopandas as gpd
import matplotlib.font_manager as fm
from Analyst import Network
from GeoLearning.Supervised import Regression
from Sandbox import proxy_indicators, proxy_network, overlay_radius
from UrbanMobility.SB0_Variables import *
from matplotlib import rc
from sklearn.ensemble import RandomForestRegressor

fm.fontManager.ttflist += fm.createFontList(['/Volumes/Samsung_T5/Fonts/roboto/Roboto-Light.ttf'])
rc('font', family='Roboto', weight='light')


def analyze_sandbox(buildings, parcels, streets, export=True, ch_dir=os.getcwd(), sb_name='Sandbox', suffix='e0'):
    # print(f"Analyzing {experiments} sandboxes")
    # for sandbox, value in experiments.items():
    #     proxy = Network(f'{sandbox} Sandbox', crs=26910, directory=f'{directory}Sandbox/{sandbox}', nodes='network_intersections')
    #     db_layers = listlayers(proxy.gpkg)
    #
    #     # Check if sandbox has links and intersections
    #     network = ['network_links', 'network_intersections', 'land_municipal_boundary']
    #     for layer in network:
    #         if layer not in db_layers:
    #             raise AttributeError(f"{layer} not found in GeoPackage of {sandbox}")
    #
    #     for code, year in experiments[sandbox][1].items():
    #         # Check if experiment has parcels and buildings
    #         built = [f'land_parcels_{code}', f'fabric_buildings_{code}']
    #         for layer in built:
    #             if layer not in db_layers:
    #                 raise AttributeError(f"{layer} not found in GeoPackage of {sandbox}")

    # Standardize directory
    if ch_dir[-1:] == '/': ch_dir = ch_dir[:-1]
    else: ch_dir = ch_dir

    # Define geographic boundary
    sandbox = sb_name
    proxy = Network(f'{sandbox} Sandbox', crs=26910, directory=f'{ch_dir}/Sandbox/{sandbox}', nodes='network_intersections')

    # Save parcels, buildings and streets on local_gbd GeoPackage
    streets.to_file(proxy.gpkg, layer='network_links', driver='GPKG')
    parcels.to_file(proxy.gpkg, layer=f'land_parcels_{suffix}', driver='GPKG')
    buildings.to_file(proxy.gpkg, layer=f'fabric_buildings_{suffix}', driver='GPKG')

    # Transfer network indicators to sandbox
    proxy = proxy_network(proxy)

    # Extract elevation data
    proxy.node_elevation()

    # Calculate spatial indicators
    proxy = proxy_indicators(proxy, experiment={suffix: 2020})

    # Perform network analysis
    results = proxy.network_analysis(
        run=True,
        col_prefix='mob',
        file_prefix=f'mob_{suffix}',
        service_areas=radii,
        sample_gdf=gpd.read_file(proxy.gpkg, layer=f"land_parcels_{suffix}"),
        aggregated_layers=network_layers,
        keep=['OBJECTID', "population, 2016"],
        export=export)

    # # Divide sums aggregations to a buffer overlay in order to avoid edge effects
    # for col in results.columns:
    #     if '_sum_' in col:
    #         results[col] = results[col]/results['divider']

    gc.collect()
    return results

def rename_features(rename):
    rename_dict2 = {}
    rename_dict3 = {}
    type_dict2 = {}

    for k, value in rename.items():
        v = value[0]
        rename_dict3[k] = v
        for r in radii:
            for d in ['l', 'f']:
                for op in ['ave', 'sum', 'cnt', 'rng']:
                    if op == 'ave':
                        t = 'Average'
                    elif op == 'sum':
                        t = 'Total'
                    else:
                        t = ''
                    renamed = f'{t} '
                    item = f'{renamed}{v.lower()} within {r}m'
                    rename_dict2[f"{k}_r{r}_{op}_{d}"] = f'{item.strip()[0].upper()}{item.strip()[1:]}'
                    type_dict2[f"{k}_r{r}_{op}_{d}"] = value[1]
    rename = {**rename_dict2, **rename_dict3}
    return rename

def train_regression(training, testing, radii, label_cols, rename, suffix='', ch_dir='', random_seeds=6):
    proxy_files2 = list(testing.values())

    rename = rename_features(rename)

    for rs in range(random_seeds):
        # Filter columns common to proxy and dissemination areas
        ind_cols = [set(gdf.columns) for gdf in training]+[set(f.columns) for f in proxy_files2]
        common_cols = list(set.intersection(*ind_cols))
        final_cols = [col for col in common_cols if col in list(rename.keys())]
        training = [gdf.loc[:, final_cols + label_cols] for gdf in training]

        print(f"\nStarting regression with random seed {rs}")
        reg = Regression(
            r_seed=rs,
            test_split=0.2,
            n_indicators=5,
            round_f=4,
            norm_x=False,
            norm_y=False,
            data=training,
            directory=ch_dir,
            predicted=label_cols,
            prefix=f'',
            rename=rename,
            filter_pv=False,
            plot=True,
            pv=0.05,
            file_suffix=f"{suffix}_{rs}",
            color_by="Population density per square kilometre, 2016",
        )

        # Run random forest and partial dependence plots
        reg.non_linear(method=RandomForestRegressor)
        reg.test_non_linear(i_method='regular')

        features = reg.partial_dependence(n_features=9)
        reg.save_model()
        return reg

def test_regression(proxy_gdf, label_cols, random_seeds=6, ch_dir=os.getcwd(), suffix=''):

    # Create regression object
    reg = Regression(
        test_split=0.2,
        n_indicators=5,
        round_f=4,
        norm_x=False,
        norm_y=False,
        directory=ch_dir,
        predicted=label_cols,
        prefix=f'',
        filter_pv=False,
        plot=True,
        pv=0.05,
        color_by="Population density per square kilometre, 2016",
    )

    # Iterate over proxy files
    all_seeds = proxy_gdf.copy()
    for rs in range(random_seeds):
        print(f"\nStarting regression with random seed {rs}")
        reg.r_seed = rs
        reg.fitted = pickle.load(open(f'Trained/FittedModel_Sunset_{rs}.sav', 'rb'))
        reg.train_data = pickle.load(open(f'Trained/TrainData_Sunset_{rs}.sav', 'rb'))

        # Predict sandbox using random forest
        proxy_gdf_rs = reg.pre_norm_exp(proxy_gdf, prefix=f'rf_{rs}')
        gc.collect()

        # Append prediction to all_seeds
        all_seeds = pd.concat([all_seeds, proxy_gdf_rs.loc[:,
            [f'{mode}_rf_{rs}_n' for mode in reg.label_cols]
        ]], axis=1)

        # Get most important features

    # Average random seeds
    for label in label_cols:
        all_seeds[label] = all_seeds.loc[:, [f'{label}_rf_{rs}_n' for rs in range(random_seeds)]].mean(axis=1)

    # Return parcels with predicted mode shares
    gc.collect()
    return all_seeds

directory = '/Volumes/Samsung_T5/Databases'
rename_dict = {
    'mob_network_stops_ct': ('Public transit stops', 'network'),
    'mob_frequency': ('Transit frequency', 'network'),
    # 'mob_network_nodes_ct': ('Number of intersections', 'network'),
    # 'mob_elevation': ('Elevation', 'network'),

    # 'mob_connectivity': ('Axial connectivity', 'network'),
    # 'mob_axial_closeness': ('Axial closeness centrality', 'network'),
    # 'mob_axial_betweenness': ('Axial betweenness centrality', 'network'),
    # 'mob_axial_n_betweenness': ('Normalized axial betweenness centrality', 'network'),
    # 'mob_axial_length': ('Axial line length', 'network'),
    # 'mob_axial_eigenvector': ('Axial eigenvector centrality', 'network'),
    # 'mob_axial_katz': ('Axial katz centrality', 'network'),
    # 'mob_axial_pagerank': ('Axial page rank centrality', 'network'),
    # 'mob_axial_hits1': ('Axial hits centrality', 'network'),
    # 'mob_axial_degree': ('Axial degree centrality', 'network'),

    'mob_network_walk_ct': ('Intensity of walkable Network', 'network'),
    'mob_network_bike_ct': ('Intensity of bikeable Network', 'network'),
    'mob_network_drive_ct': ('Intensity of driveable Network', 'network'),
    'mob_walk_length': ('Length of walkable Network', 'network'),
    'mob_bike_length': ('Length of bikeable Network', 'network'),
    'mob_drive_length': ('Length of driveable Network', 'network'),
    # 'mob_walk_straight': ('Straightness of walkable Network', 'network'),
    # 'mob_bike_straight': ('Straightness of bikeable Network', 'network'),
    # 'mob_drive_straight': ('Straightness of driveable Network', 'network'),

    'mob_land_assessment_fabric_ct': ('Number of units', 'density'),
    'mob_n_use': ('Use diversity', 'landuse'),
    'mob_CM': ('Commercial', 'landuse'),
    'mob_SFD': ('Single-Family Detached', 'landuse'),
    'mob_SFA': ('Single-Family Attached', 'landuse'),
    'mob_MFL': ('Multi-Family Low-Rise', 'landuse'),
    'mob_MFH': ('Multi-Family High-Rise', 'landuse'),
    'mob_MX': ('Mixed Use', 'landuse'),
    'mob_total_finished_area': ('Total finished area', 'density'),
    'mob_gross_building_area': ('Gross building area', 'density'),
    'mob_number_of_bedrooms': ('Number of bedrooms', 'density'),

    # 'mob_land_assessment_parcels_ct': ('Number of parcels', 'density'),
    # 'mob_area_sqkm': ('Parcel size', 'density'),
    # 'mob_n_size': ('Parcel diversity', 'density'),

    'mob_population density per square kilometre, 2016': ('Population density', 'density'),
    'mob_n_dwellings': ('Number of dwellings', 'density'),
    'mob_population, 2016': ('Population', 'density'),

}
infra_dict = {
    'bus': {
        'mob_frequency': ('Transit frequency', 'network'),
        'mob_network_stops_ct': ('Public transit stops', 'network'),
    },
    'bike': {
        'mob_cycle_length': ('Cycling network length', 'network'),
    }
}
