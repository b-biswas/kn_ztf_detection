import numpy as np
import pandas as pd
from scipy.optimize import minimize

from kndetect.utils import extract_mimic_alerts_region

# from tqdm import tqdm


def get_feature_names(npcs=3):
    """
    Create the list of feature names depending on the number of principal components.

    Parameters
    ----------
    npcs : int
        number of principal components to use

    Returns
    -------
    list
        name of the features.

    """
    names_root = ["coeff" + str(i + 1) + "_" for i in range(npcs)] + [
        "residuo_",
        "maxflux_",
    ]

    return [i + j for j in ["g", "r"] for i in names_root]


def calc_prediction(coeff, pcs_arr):
    """
    given the coefficients and PCs, it calculates the prediction as a linear combination

    Parameters
    ----------
    coeff: np.array of shape [num_pcs]
        coefficients of the linear combinations for the PCs
    pcs_arr: np.array of shape [num_pcs, num_prediction_points]
        The PCs that are being used as templates

    Returns
    -------
    predicted_lc: np.array of shape [num_prediction_points]
        prediction as a linear comination of PCs
    """
    predicted_lc = np.zeros_like(pcs_arr.shape[0])
    for a, b in zip(pcs_arr, coeff):
        predicted_lc = np.add(predicted_lc, b * a)

    return predicted_lc


def calc_loss(
    coeff,
    pcs_arr,
    light_curve_flux,
    light_curve_err,
    map_dates_to_arr_index,
    regularization_weight,
    low_var_indices=[1, 2],
):
    """
    function to calculate the loss to be optimized

    Parameters
    ----------
    coeff: np.array of shape [num_of_pcs]
        current value of coefficients
    pcs_arr: np.array of shape [num_pcs, num_prediction_points]
        principal components to the used for the prediction
    light_curve_flux: pandas column of shape [num_recorded_points]
        segment of lightcurve that is to be fitted
    light_curve_err: pandas column of shape [num_recorded_points]
        segment with corresponding error bars in the segment that is to be fitted.
    map_dates_to_arr_index: np.array of shape [num_recorded_points]
        maping that holds the index position corresponding to each point in the lightcurve
    regularization_weight: float
        weights given to the regularization term
    low_var_indices: list
        Indices along which variance is low.
        Default value is set to [1, 2] which regularizes the 2nd and 3rd PCs

    Returns
    -------
    loss: (float)
        that is to be optimized
    """
    # calculation of the reconstruction loss
    y_pred = calc_prediction(coeff, pcs_arr)
    real_flux = np.take(y_pred, map_dates_to_arr_index)
    reconstruction_loss = np.sum(
        np.divide(np.square(real_flux - light_curve_flux), np.square(light_curve_err))
    )

    # Calculate the regularization

    # Regularize the second coefficient
    regularization_term = 0
    if low_var_indices is not None:
        regularization_term = np.sum(np.square(coeff[low_var_indices[:]]))

    # Regularize negative pcscoeff = 0
    if coeff[0] < 0:
        regularization_term = regularization_term + np.square(coeff[0])

    loss = reconstruction_loss + regularization_term * regularization_weight

    return loss


def calc_residual(
    coeff, pcs_arr, light_curve_flux, light_curve_err, map_dates_to_arr_index
):
    """
    function to calculate residual of the fit

    Parameters
    ----------
    coeff: np.array of shape [num_of_pcs]
        current value of coefficients
    pcs: np.array of shape [num_pcs, num_prediction_points]
        principal components to the used for the prediction
    light_curve_flux: pandas column of shape [num_recorded_points]
        segment of lightcurve that is to be fitted
    light_curve_err: pandas column of shape [num_recorded_points]
        segment with corresponding error bars in the segment that is to be fitted.
    map_dates_to_arr_index: np.array of shape [num_recorded_points]
        maping that holds the index position corresponding to each point in the lightcurve

    Returns
    -------
    residual: float
        residual value
    """

    y_pred = calc_prediction(coeff, pcs_arr)
    real_flux = np.take(y_pred, map_dates_to_arr_index)

    diff = real_flux - light_curve_flux
    reconstruction_loss = np.mean(
        np.divide(np.square(diff), np.square(light_curve_err))
    )

    residual = np.sqrt(reconstruction_loss)
    return residual


def predict_band_features(
    band_df, pcs, time_bin=0.25, flux_lim=200, low_var_indices=[1, 2]
):
    """
    function to evaluate features for a band

    Parameters
    ----------
    band_df: pandas.DataFrame
        dataframe with the data of only one band of a lightcurve
    pcs: np.array of shape [num pc components, num prediction points/bins]
        For example, pcs_arr[0] will correspond the the first principal component.
    time_bin: float
        Width of time gap between two elements in PCs.
    flux_lim: float (optional)
        Limit of minimum flux for prediction to be made in a band.
        Note that all the points in the band is used for the fit provided that max flux in the band > flux_lim
    low_var_indices: list
        Indices along which variance is low.
        Default value is set to [1, 2] which regularizes the 2nd and 3rd PCs

    Returns
    -------
    features: list of features for the given band
        The features are in the same order in which the classifier was trained:
        coefficients of pcs, number of features, residual and maxflux.
    """

    num_pcs = len(pcs)
    num_prediction_points = len(pcs[0])

    if len(band_df) == 0:
        features = np.zeros(int(len(get_feature_names(num_pcs)) / 2)).tolist()
        return features

    max_loc = np.argmax(band_df["FLUXCAL"])
    max_flux = band_df["FLUXCAL"].iloc[max_loc]

    # extract the prediction region
    mid_point_date = band_df["MJD"].iloc[max_loc]

    prediction_duration = time_bin * (num_prediction_points - 1)

    start_date = mid_point_date - prediction_duration / 2
    end_date = mid_point_date + prediction_duration / 2

    duration_index = (band_df["MJD"] > start_date) & (band_df["MJD"] < end_date)
    band_df = band_df[duration_index]

    if (max_flux > flux_lim) & (len(band_df) >= 2):

        # update the location
        max_loc = np.argmax(band_df["FLUXCAL"])

        # create a mapping from JD to index in the prediction.
        # For Example, midpoint is at index (num_prediction_points - 1) / 2. The middle of the prediction region.
        map_dates_to_arr_index = np.around(
            (band_df["MJD"].values - mid_point_date).astype(float) / time_bin
            + (num_prediction_points - 1) / 2
        )
        map_dates_to_arr_index = map_dates_to_arr_index.astype(int)

        # Initil guess for coefficients.
        initial_guess = np.zeros(num_pcs) + 0.5

        # Calculating the regularization weight to make it comparable to reconstruction loss part.
        err_bar_of_max_flux = band_df["FLUXCALERR"].iloc[max_loc]

        regularization_weight = np.square(max_flux / err_bar_of_max_flux)

        # normalize the flux and errorbars
        normalized_flux = band_df["FLUXCAL"].values / max_flux
        normalized_err_bars = band_df["FLUXCALERR"].values / max_flux

        # bounds for the coefficient
        bounds = []
        for i in range(num_pcs):
            bounds.append([-2, 2])

        # minimize the cost function
        result = minimize(
            calc_loss,
            initial_guess,
            args=(
                pcs,
                normalized_flux,
                normalized_err_bars,
                map_dates_to_arr_index,
                regularization_weight,
                low_var_indices,
            ),
            bounds=bounds,
        )

        # extract the coefficients
        coeff = list(result.x)

        # maximum flux in a band
        max_band_flux = max_flux

        # calculate residuals
        residual = calc_residual(
            result.x, pcs, normalized_flux, normalized_err_bars, map_dates_to_arr_index
        )

    else:
        coeff = np.zeros(num_pcs).tolist()
        residual = 0
        max_band_flux = 0

    # buid features list
    features = coeff
    features.append(residual)
    features.append(max_band_flux)

    return features


def extract_features_all_bands(pcs, filters, lc, flux_lim, time_bin):
    """
    Extract features for all the bands of lightcurve
    Parameters
    ----------
    pcs: np.array of shape [num_pcs, num_prediction_points]
        principal components to the used for the prediction
    time_bin: float
        Width of time gap between two elements in PCs.
    filters: list
        List of broad band filters.
    lc: pd.DataFrame
        Keys should be ['MJD', 'FLUXCAL', 'FLUXCALERR', 'FLT'].
    flux_lim: float (optional)
        Limit of minimum flux for prediction to be made in a band.
        Note that all the points in the band is used for the fit provided that max flux in the band > flux_lim
    low_var_indices: list
        Indices along which variance is low.
        Default value is set to [1, 2] which regularizes the 2nd, 3rd PCs
    flux_lim: int/float
        flux value above which no predictions are made for a band
    time_bin:
        duration of a time bin in days. For eg, .25 means 6 hours

    Returns
    -------
    all_features: list
        List of features for this object.
        Order is all features from first filter, then all features from
        second filters, etc.
    """

    low_var_indices = [1, 2]
    all_features = []

    for band in filters:

        band_df = lc[lc["FLT"] == band]
        features = predict_band_features(
            band_df=band_df,
            pcs=pcs,
            time_bin=time_bin,
            flux_lim=flux_lim,
            low_var_indices=low_var_indices,
        )

        all_features.extend(features)

    return all_features


def extract_features_all_lightcurves(lc_df, key, pcs, filters, mimic_alerts=False):
    """
    extracts features for all lightcurves in df

    Parameters:
    lc_df: pandas DataFrame
        dataframe with data of differnet lightcurves.
        Columns must include: "MJD", "FLT", "FLUXCAL", "FLUXCALERR" and a key
    key: str
        Column name to identify each lightcurve to be fitted.
    pcs: np.array of shape [num_pcs, num_prediction_points]
        principal components to the used for the prediction
    filters: list
        list of filters/bands present in the lightcurves
    minic_alerts: bool
        boolean value to choose beetween extracting features for complete light curves or partical lightcurves.
    """
    time_bin = 0.25  # 6 hours
    flux_lim = 200
    object_ids = np.unique(lc_df[key])
    feature_names = get_feature_names()
    features_df = {k: [] for k in feature_names}
    features_df["key"] = []
    current_dates = []

    for object_id in object_ids:
        object_lc = lc_df[lc_df[key] == object_id]
        object_lc = object_lc[object_lc["FLUXCAL"] == object_lc["FLUXCAL"]]
        if mimic_alerts:
            object_lc, current_date = extract_mimic_alerts_region(object_lc, flux_lim)
            current_dates.append(current_date)
        features = extract_features_all_bands(
            pcs=pcs, filters=filters, lc=object_lc, flux_lim=flux_lim, time_bin=time_bin
        )
        features_df["key"].append(object_id)
        for i, feature_name in enumerate(feature_names):
            features_df[feature_name].append(features[i])

    if mimic_alerts:
        features_df["current_dates"] = current_dates
        return pd.DataFrame.from_dict(features_df)

    return pd.DataFrame.from_dict(features_df)
