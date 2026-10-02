// Only this separate preview origin gets a sample list. The user's real app is untouched.
const headerQuery = new URLSearchParams(location.search).get('header_option');
const headerChoice = ['1','2','3','4'].includes(headerQuery) ? headerQuery : sessionStorage.getItem('header-choice') || '1';
document.documentElement.dataset.headerOption = headerChoice;
sessionStorage.setItem('header-choice', headerChoice);
if (!localStorage.getItem('couchside-v1')) {
  localStorage.setItem('couchside-v1', JSON.stringify({version:3,onboarded:true,profile:[],saved:[
    {id:169,name:'Breaking Bad',year:2008,poster:'https://static.tvmaze.com/uploads/images/medium_portrait/501/1253519.jpg'},
    {id:618,name:'Better Call Saul',year:2015,poster:'https://static.tvmaze.com/uploads/images/medium_portrait/501/1253515.jpg'}
  ],settings:{known_min:85}}));
}
