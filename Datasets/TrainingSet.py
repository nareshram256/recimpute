"""
RecImpute - A Recommendation System of Imputation Techniques for Missing Values in Time Series,
eXascale Infolab, University of Fribourg, Switzerland
***
TrainingSet.py
@author: @chacungu
"""

from imblearn.over_sampling import SMOTE
import numpy as np
import pandas as pd
import random as rdm
from sklearn.model_selection import train_test_split as sklearn_train_test_split
import warnings

from Datasets.Dataset import Dataset
from Utils.Utils import Utils

class TrainingSet:
    """
    Class which handles a training set to be used in classification / regression tasks.
    """

    CONF = Utils.read_conf_file('trainingset')


    # constructor

    def __init__(self, datasets, clusterer, features_extracters, labeler, labeler_properties, 
                 true_labeler=None, true_labeler_properties=None, force_generation=False):
        """
        Initializes a TrainingSet object.

        Keyword arguments:
        datasets -- list of Dataset objects
        clusterer -- instance of a clusterer
        features_extracters -- list of instances of features extracters
        labeler -- instance of a labeler used to label training set
        labeler_properties -- dict specifying the labeler's label properties
        true_labeler -- instance of a "true" labeler used to label only the test set (default None: use the labeler)
        true_labeler_properties -- dict specifying the true_labeler's label properties (default None: use the labeler's properties)
        force_generation -- True if the clusters, labels, and features must be created even if they already exist, False otherwise
        """
        assert (true_labeler is None and true_labeler_properties is None) or \
               (true_labeler is not None and true_labeler_properties is not None)
        self.clusterer = clusterer
        self.labeler = labeler
        self.labeler_properties = labeler_properties
        self.true_labeler = true_labeler
        self.true_labeler_properties = true_labeler_properties
        self.features_extracters = features_extracters # list

        rdm.seed(TrainingSet.CONF['RDM_SEED'])
        np.random.seed(TrainingSet.CONF['RDM_SEED'])
        
        # make sure clustering has been done (and do it otherwise)
        print('Running clustering (if not done already).')
        updated_datasets, clusters_created = self.__init_clustering(datasets, force_generation)
        print('Clustering done.')

        # reserve some data for testing
        self.test_set_level, self.test_set_ids = self.__init_test_set(datasets, 
                                                                      TrainingSet.CONF['TEST_SET_RESERVATION_STRAT'])

        # make sure labeling & features extraction has been done (and do it otherwise)
        print('Running labeling & features extraction (if not done already).')
        updated_datasets = self.__init_labeling_and_fe(updated_datasets, force_generation | clusters_created)
        print('Labeling & features extraction done.')
        self.datasets = updated_datasets

    def __init_test_set(self, datasets, strategy):
        """
        Reserves some data for testing according to the specified strategy.

        Keyword arguments:
        datasets -- list of Dataset objects
        strategy -- string specifying the test set reservation strategy
        
        Return:
        1. string specifying the level at which data is reserved (clusters or datasets)
        2. list of ids to identify the data reserved for testing
        """
        if strategy == 'one_cluster_every_two_dataset':
            # reserve one cluster every two data sets for the test set
            test_set = []
            for dataset in datasets[::2]:
                for cid in dataset.cids:
                    test_set.append(cid)
                    break
            return 'clusters', test_set
        else:
            raise Exception('Test set reservation strategy not implemented: ', strategy)

    def __init_clustering(self, datasets, force_generation):
        """
        Makes sure each data set's clustering has already been done. If not, finds the missing clusters.

        Keyword arguments:
        datasets -- list of Dataset objects containing the time series to cluster.
        force_generation -- boolean to indicate if the clusters must be generated even if they already exist
        
        Return:
        1. List of Dataset objects
        2. True if some data set's were missing clusters and must have been clustered, False otherwise
        """
        clusters_generated = False
        updated_datasets = []
        for dataset in datasets:
            if not dataset.are_clusters_created():
                # create clusters if they have not been yet created for this data set
                if not clusters_generated:
                    warnings.warn('Some data set\'s time series have not been clustered yet. \
                                    They will be clustered now. Clustering data sets one-by-one is \
                                    less-efficient than using the clusterer\'s method "cluster_all_datasets" \
                                    before the instantiation of a TrainingSet object.')
                dataset = self.clusterer.cluster(dataset)
                clusters_generated = True
            updated_datasets.append(dataset)
        if clusters_generated:
            # merge clusters with <5 time series to the most similar cluster from the same data set
            updated_datasets = self.clusterer.merge_small_clusters(updated_datasets, min_nb_ts=self.clusterer.CONF['MIN_NB_TS_PER_CLUSTER'])
        if clusters_generated or not self.clusterer.are_cids_unique(updated_datasets):
            # change all clusters' ID (for all datasets) such that there are no duplicates
            updated_datasets = self.clusterer.make_cids_unique(updated_datasets)

        return updated_datasets, clusters_generated

    def __init_labeling_and_fe(self, datasets, force_generation):
        """
        Makes sure each data set's labels and features have already been created. If not, creates the missing ones.

        Keyword arguments:
        datasets -- list of Dataset objects
        force_generation -- boolean to indicate if the labels & features must be generated even if they already exist
        
        Return:
        List of Dataset objects
        """
        updated_datasets = []
        for dataset in datasets:
            # labeling
            if force_generation or not self.labeler.are_labels_created(dataset.name):
                # create labels if they have not been yet created for this data set
                dataset = self.labeler.label(dataset)
            if self.true_labeler is not None and self.is_in_test_set(dataset): 
                if force_generation or not self.true_labeler.are_labels_created(dataset.name):
                    # create true labels if they have not been yet created for this data set
                    dataset = self.true_labeler.label(dataset)

            # features extraction
            for features_extracter in self.features_extracters:
                if force_generation or not features_extracter.are_features_created(dataset.name):
                    # create features if they have not been yet created for this data set
                    dataset = features_extracter.extract(dataset)
            updated_datasets.append(dataset)

        return updated_datasets


    # public methods

    def get_test_set(self):
        """
        Returns the test set.

        Keyword arguments: -
        
        Return:
        1. Pandas DataFrame containing all time series' features (one feature vector per row). Index: Time Series ID.
        2. Pandas DataFrame containing all time series' labels. Index: Time Series ID.
        3. list of all unique labels
        """
        all_data_info, labels_set = self._load(test_set=True)
        data = all_data_info.iloc[:, ~all_data_info.columns.isin(['Cluster ID', 'Label'])]
        labels = all_data_info['Label']
        return data, labels, labels_set

    def yield_splitted_train_val(self, data_properties, nb_cv_splits):
        """
        Yields splitted train and validation sets.

        Keyword arguments:
        data_properties -- dict specifying the data's properties (e.g. should it be balanced, reduced, etc.)
        nb_cv_splits -- number of cross-validation splits to perform
        
        Return:
        1. Pandas DataFrame containing all time series' features (one feature vector per row). Index: Time Series ID.
        2. Pandas DataFrame containing all time series' labels. Index: Time Series ID.
        3. list of all unique labels
        4. Numpy array of train entries
        5. Numpy array of train entries' labels
        6. Numpy array of validation entries
        7. Numpy array of validation entries' labels
        """
        all_data_info, labels_set = self._load(test_set=False)
        # all_data_info: df w/ cols: Time Series ID (index), Cluster ID, Label, Feature 1's name, Feature 2's name, ...
        
        # reduce the data set if required
        if data_properties['usable_data_perc'] < 1.0:
            all_data_info = self._reduce_data_set(all_data_info, data_properties['usable_data_perc'])

        # balance the data set if required
        if data_properties['balance'] is not None:
            all_data_info = self._balance_data_set(all_data_info, data_properties['balance'])

        # init probability distribution for data splitting
        probability_distribution = np.full(all_data_info['Cluster ID'].nunique(), 1 / all_data_info['Cluster ID'].nunique())

        for cv_split_id in range(nb_cv_splits):
            train_indices, test_indices, train_cids = self._split_train_test_sets(all_data_info, probability_distribution, 
                                                                                  TrainingSet.CONF['VALIDATION_SIZE_PERCENTAGE'])
            probability_distribution = self._update_prob_distrib(all_data_info, probability_distribution, train_cids)

            data = all_data_info.iloc[:, ~all_data_info.columns.isin(['Cluster ID', 'Label'])]
            labels = all_data_info['Label']

            # split train/val sets
            X_train = data.loc[train_indices, :][:].to_numpy().astype('float32')
            y_train = labels.loc[train_indices].to_numpy().astype('str')
            X_val = data.loc[test_indices, :][:].to_numpy().astype('float32')
            y_val = labels.loc[test_indices].to_numpy().astype('str')

            # augment training data
            if data_properties['augment']:
                X_train, y_train = self._augment_train(X_train, y_train)

            yield data, labels, labels_set, X_train, y_train, X_val, y_val

    def is_in_test_set(self, dataset):
        """
        Checks whether any of the data set's cluster or the whole data set are in the test set.

        Keyword arguments:
        dataset -- Dataset object
        
        Return:
        True if any of the data set's cluster or the whole data set are in the test set, False otherwise
        """
        if self.test_set_level == 'clusters':
            return any(cid in self.test_set_ids for cid in dataset.cids)
        elif self.test_set_level == 'datasets':
            return dataset.name in self.test_set_ids
        else:
            raise Exception('Test set reservation strategy not implemented: ', TrainingSet.CONF['TEST_SET_RESERVATION_STRAT'])

    def get_labeler_properties(self):
        """
        Returns the training set's labeler labels properties.

        Keyword arguments: -

        Return:
        dict specifying the labeler's label properties
        """
        return self.labeler_properties

    def get_default_properties(self):
        """
        Returns the default data properties in a dict.
        
        Keyword arguments: -
        
        Return: 
        dict of default data properties
        """
        return TrainingSet.CONF['DATA_PROPERTIES']


    # private methods

    def _load(self, test_set):
        """
        Loads the labels, features, and clusters' assignment of each data set's time series.

        Keyword arguments:
        test_set -- set to True if the data to load is from the test set, False if it is the training and 
                    validation sets.
        
        Return:
        1. Pandas DataFrame containing the loaded labels, features, and clusters' assignment of each data set's 
           time series (each row is for one time series). Columns: Time Series ID (index), Cluster ID, Label, 
           Feature 1's name, Feature 2's name, ...
        2. list of all unique labels
        """
        labels_set = None
        all_complete_datasets = []
        all_train_test_complete_datasets = []
        for dataset in self.datasets:

            # load labels - dataset_labels: df w/ 2 cols: Time Series ID and Label
            dataset_labels, labels_set = dataset.load_labels(self.labeler, self.labeler_properties)
            dataset_labels.set_index('Time Series ID', inplace=True)

            # load features - dataset_features: df w/ cols: Time Series ID, (Cluster ID), Feature 1's name, Feature 2's name, ...
            all_dataset_features = []
            for features_extracter in self.features_extracters:
                tmp_dataset_features = dataset.load_features(features_extracter)
                tmp_dataset_features.set_index('Time Series ID', inplace=True)
                all_dataset_features.append(tmp_dataset_features)
            dataset_features = pd.concat(all_dataset_features, axis=1) # concat features dataframes

            to_concat = [dataset_labels, dataset_features]

            # load cassignment if the column is not there already
            if 'Cluster ID' not in dataset_features.columns:
                dataset_cassignment = dataset.load_cassignment()
                dataset_cassignment.set_index('Time Series ID', inplace=True)
                to_concat.append(dataset_cassignment)

            # concat data set's labels, features and cassignment
            complete_dataset = pd.concat(to_concat, axis=1)

            all_train_test_complete_datasets.append(complete_dataset) # this list contains train, val & test sets
            
            # only keep either the test set or the training and validation sets
            if self.test_set_level == 'clusters':
                if test_set:
                    complete_dataset = complete_dataset.loc[complete_dataset['Cluster ID'].isin(self.test_set_ids)]
                else:
                    complete_dataset = complete_dataset.loc[~complete_dataset['Cluster ID'].isin(self.test_set_ids)]
            elif self.test_set_level == 'datasets':
                if test_set and dataset.name in self.test_set_ids:
                    pass
                else:
                    continue # the whole data set is in the test set but we want the train & val sets: skip this data set
            else:
                raise Exception('Test set reservation strategy not implemented: ', TrainingSet.CONF['TEST_SET_RESERVATION_STRAT'])

            all_complete_datasets.append(complete_dataset) # this list contains either train & val sets or test set
        
        # merge the complete data sets (each row is a time serie's info)
        all_train_test_complete_datasets_df = pd.concat(all_train_test_complete_datasets, axis=0)
        all_complete_datasets_df = pd.concat(all_complete_datasets, axis=0)

        # drop columns that contain NaN values (feature columns that not all data sets can have)
        # do this on the df that contains ALL data (train, val & test sets)
        nb_cols = all_train_test_complete_datasets_df.shape[1]
        all_train_test_complete_datasets_df = all_train_test_complete_datasets_df.dropna(axis=1)
        nb_dropped_cols = all_train_test_complete_datasets_df.shape[1] - nb_cols
        if nb_dropped_cols > nb_cols / 10:
            warnings.warn("Warning: %i/%i feature columns were dropped because they contained NaN values!" % (nb_dropped_cols, nb_cols))
        
        # only keep the columns with no NaN in either train, val & test sets
        all_complete_datasets_df = all_complete_datasets_df[all_train_test_complete_datasets_df.columns]
        
        assert labels_set is not None
        return all_complete_datasets_df, labels_set

    def _balance_data_set(self, all_data_info, according_to):
        """
        Balances the data set according to the specified column values (clusters or labels).

        Keyword arguments:
        all_data_info -- Pandas DataFrame containing the loaded labels, features, and clusters' assignment of each data set's 
                         time series (each row is for one time series). Columns: Time Series ID (index), Cluster ID, Label, 
                         Feature 1's name, Feature 2's name, ...
        according_to -- string identifying the column according to which the data set should be balanced
        
        Return:
        Balanced Pandas DataFrame. Columns: Time Series ID (index), Cluster ID, Label, Feature 1's name, Feature 2's name, ...
        """    
        column_name = None
        if according_to == 'clusters':
            column_name = 'Cluster ID'
        elif according_to == 'labels':
            column_name = 'Label'
        else:
            raise Exception('Invalid argument "according_to" for balancing data set: ', according_to)

        balanced_df = pd.DataFrame(columns=all_data_info.columns)
        # get number of time series in smallest cluster or less-attributed class (depending on attr. "according_to")
        n = all_data_info[column_name].value_counts().min()
        # for each id in the reference column
        for col_id in all_data_info[column_name].unique():
            # sample n random time series with this id
            rows = all_data_info[all_data_info[column_name] == col_id].sample(n)
            balanced_df = balanced_df.append(rows)
        return balanced_df

    def _reduce_data_set(self, all_data_info, usable_data_perc):
        """
        Selects and returns a specified percentage of the data. Splits the data in a stratified fashion according 
        to the time series labels.

        Keyword arguments:
        all_data_info -- Pandas DataFrame containing the loaded labels, features, and clusters' assignment of each data set's 
                         time series (each row is for one time series). Columns: Time Series ID (index), Cluster ID, Label, 
                         Feature 1's name, Feature 2's name, ...
        usable_data_perc -- percentage of time series to keep
        
        Return:
        Reduced Pandas DataFrame. Columns: Time Series ID (index), Cluster ID, Label, Feature 1's name, Feature 2's name, ...
        """    
        reduced_train_val_df, _, _, _ = sklearn_train_test_split(all_data_info, 
                                                                 all_data_info['Label'], 
                                                                 train_size=usable_data_perc, 
                                                                 stratify=all_data_info['Label'])
        return reduced_train_val_df

    def _split_train_test_sets(self, all_data_info, probability_distribution, val_size):
        """
        Split time series' DataFrame into random train and validation subsets.
        
        Keyword arguments:
        all_data_info -- Pandas DataFrame containing each data set's time series information (ID, CID, labels, features)
        probability_distribution -- sequence of probabilities associated with each cluster id
        val_size -- proportion of the data set to include in the validation split
        
        Return:
        1. List containing train indices (Time Series ID).
        2. List containing validation indices (Time Series ID).
        3. List containing the indices of the clusters used for training.
        """
        cids_value_counts = all_data_info['Cluster ID'].value_counts()
    
        train = {'cids': [], 'nb_timeseries': []}
        test = {'cids': [], 'nb_timeseries': []}
        
        # select random cluster (based on the given distribution) and add all its time series to the training set
        for cluster_id in np.random.choice(sorted(all_data_info['Cluster ID'].unique(), key=int), 
                                           all_data_info['Cluster ID'].nunique(), 
                                           replace=False,
                                           p=probability_distribution):
            if (sum(train['nb_timeseries']) / len(all_data_info)) < (1 - val_size - (0.25 * val_size)):
                train['cids'].append(cluster_id)
                train['nb_timeseries'].append(cids_value_counts[cluster_id])
            else:
                test['cids'].append(cluster_id)
                test['nb_timeseries'].append(cids_value_counts[cluster_id])
                
        train_indices, test_indices = [], []
        
        for tid, row in all_data_info.iterrows():
            if row['Cluster ID'] in train['cids']:
                train_indices.append(tid)
            else:
                test_indices.append(tid)
        
        return rdm.sample(train_indices, len(train_indices)), rdm.sample(test_indices, len(test_indices)), train['cids']

    def _update_prob_distrib(self, all_data_info, probability_distribution, train_ids):
        """
        Updates the probability distribution vector for clusters (prob to be attributed to the training set).
        
        Keyword arguments:
        all_data_info -- Pandas DataFrame containing each data set's time series information (ID, CID, labels, features)
        probability_distribution -- sequence of probabilities associated with each cluster id
        train_ids -- list containing the indices of the clusters used for training.
        
        Return:
        Updated probability_distribution
        """
        nb_elems = all_data_info['Cluster ID'].nunique()
        nb_not_train = nb_elems - len(train_ids) # number of elements that were not used for training during the last split
        
        if nb_not_train > 0:        
            weights_to_share = 0
            # compute weight to redistribute
            for i, (cid, w) in enumerate(zip(sorted(all_data_info['Cluster ID'].unique(), key=int), probability_distribution)):
                if cid in train_ids:
                    old_weight = probability_distribution[i]
                    probability_distribution[i] *= TrainingSet.CONF['PROB_DEC_FACTOR_AFTER_ATTRIBUTION']
                    weights_to_share += old_weight - probability_distribution[i]
                    
            # redistribute the extra weight
            for i, (cid, w) in enumerate(zip(sorted(all_data_info['Cluster ID'].unique(), key=int), probability_distribution)):
                if cid not in train_ids:
                    probability_distribution[i] += weights_to_share / nb_not_train

            assert round(sum(probability_distribution), 5) == 1.0
            return probability_distribution
        
        assert round(sum(probability_distribution), 5) == 1.0
        return probability_distribution

    def _augment_train(self, X_train, y_train):
        """
        Augments the training data using SMOTE.
        
        Keyword arguments:
        X_train -- numpy array of train entries
        y_train -- numpy array of train entries' labels
        
        Return:
        1. numpy array of augmented train entries
        2. numpy array of augmented train entries' labels
        """
        # count the minimum number of time series in the less-represented class
        min_n_samples = min(np.unique(y_train, return_counts=True)[1])

        # data augmentation is possible only if the less-represented class contains at least 2 time series
        if min_n_samples >= 2:
            sm = SMOTE(k_neighbors=(min_n_samples-1 if min_n_samples <= 5 else 5))
            # augment
            X_train_augmented, y_train_augmented = sm.fit_resample(X_train, y_train)
            return X_train_augmented, y_train_augmented

        return X_train, y_train